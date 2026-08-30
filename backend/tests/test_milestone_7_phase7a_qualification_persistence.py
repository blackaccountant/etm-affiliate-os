from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.audience.qualification_contracts import (
    DIMENSIONS, AudienceQualificationContractError, QualificationAssessmentInput,
    QualificationContext, QualificationContributionInput, QualificationRuleset,
    context_fingerprint, qualification_ruleset_fingerprint, selected_membership_fingerprint,
)
from app.models.audience import AudienceProfile, AudienceQualificationAssessment, AudienceQualificationAssessmentMembership, AudienceQualificationContribution, AudienceSegment, AudienceSegmentMembership, AudienceSegmentRevision
from app.repositories.audience_qualification_repository import AudienceQualificationRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_qualification_service import AudienceQualificationError, AudienceQualificationService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate


AS_OF = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def ruleset(version="audience-qualification-v1", *, pricing=80):
    return QualificationRuleset(
        version=version,
        dimension_contributions={"PROBLEM": ("problem_strength",), "INTEREST": ("interest_alignment",), "INTENT": ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent"), "PURCHASE": ("purchase_signal",), "ENGAGEMENT": ("engagement",), "BUSINESS_NEED": ("business_need_fit",)},
        intent_stage_multipliers={"RESEARCH": 20, "COMPARE": 40, "EVALUATE": 60, "PRICING": pricing, "PURCHASE_REQUEST": 100},
        strength_confidence_policy="MULTIPLY_CONFIDENCE_CAP", dimension_caps={key: 100 for key in DIMENSIONS},
        intent_aggregation={key: 1 for key in DIMENSIONS}, qualification_aggregation={key: 1 for key in DIMENSIONS},
        thresholds={"NOT_QUALIFIED": 0, "EARLY": 40, "QUALIFIED": 60, "HIGH_INTENT": 80},
    )


def profile_with_signal(db):
    foundation = AudienceFoundationService(db); subject = foundation.create_subject("PERSON")
    observation = foundation.ingest_observation(research_run_id=None, subject_id=subject.id, source_namespace="m7a", source_type="MANUAL", external_observation_id="m7a-signal", source_reference="m7a", observed_at=AS_OF, normalized_fact={"tag": "m7a"})
    evidence = foundation.record_evidence(observation_id=observation.id, source_reference="m7a", normalized_representation={"tag": "m7a"}, content_fingerprint="a" * 64)
    signal = AudienceSignalService(db).persist(SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "v1"), subject_id=subject.id)
    profile = AudienceProfileService(db).derive(subject.id, effective_as_of=AS_OF)
    return subject, signal, profile


def membership_for(db, profile_id):
    segment = AudienceSegment(segment_key="m7a-segment", name="M7A")
    db.add(segment); db.flush()
    revision = AudienceSegmentRevision(segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1", definition_fingerprint="b" * 64, definition_json={"all_of": [{"signal_type": "INTENT", "topic": None, "intent_stage": None, "minimum_strength": None, "minimum_confidence": None, "max_age_days": None}], "allowed_subject_types": []})
    db.add(revision); db.flush()
    membership = AudienceSegmentMembership(segment_revision_id=revision.id, profile_id=profile_id, is_member=True)
    db.add(membership); db.flush()
    return membership


def assessment(profile_id, *, selected=(), value_ruleset=None, context=None, contributions=(), dimensions=None):
    return QualificationAssessmentInput(
        profile_id=profile_id, ruleset=value_ruleset or ruleset(), context=context or QualificationContext("NONE"),
        membership_ids=tuple(selected), dimensions=dimensions or {key: 0 for key in DIMENSIONS}, intent_score=0,
        qualification_score=0, qualification_status="NOT_QUALIFIED", derived_at=AS_OF, contributions=tuple(contributions),
    )


def test_contract_fingerprints_are_canonical_and_sensitive_context_is_rejected():
    first = ruleset(); changed = ruleset(pricing=81)
    assert qualification_ruleset_fingerprint(first) == qualification_ruleset_fingerprint(ruleset())
    assert qualification_ruleset_fingerprint(first) != qualification_ruleset_fingerprint(changed)
    assert context_fingerprint(QualificationContext("TOPIC", topic="Email Deliverability")) == context_fingerprint(QualificationContext("TOPIC", topic="email_deliverability"))
    assert selected_membership_fingerprint(("b", "a")) == selected_membership_fingerprint(("a", "b"))
    with pytest.raises(AudienceQualificationContractError): QualificationContext("TOPIC", topic="political-news")
    with pytest.raises(AudienceQualificationContractError): selected_membership_fingerprint(("same", "same"))


def test_zero_assessment_reuses_without_hidden_commit_and_changed_identity_is_new(db_session):
    subject = AudienceFoundationService(db_session).create_subject("PERSON")
    profile = AudienceProfileService(db_session).derive(subject.id, effective_as_of=AS_OF)
    service = AudienceQualificationService(db_session); first_input = assessment(profile.profile_id)
    first = service.persist(first_input)
    assert db_session.in_transaction() and first.reused is False
    again = service.persist(first_input)
    assert again.assessment_id == first.assessment_id and again.reused is True
    changed_context = service.persist(assessment(profile.profile_id, context=QualificationContext("TOPIC", topic="hosting")))
    changed_ruleset = service.persist(assessment(profile.profile_id, value_ruleset=ruleset(pricing=81)))
    assert len({first.assessment_id, changed_context.assessment_id, changed_ruleset.assessment_id}) == 3
    stored = db_session.get(AudienceQualificationAssessment, first.assessment_id)
    assert stored.intent_score == stored.qualification_score == 0 and stored.qualification_status == "NOT_QUALIFIED"
    assert AudienceQualificationRepository(db_session).membership_ids(first.assessment_id) == []
    with pytest.raises(AudienceQualificationError, match="immutable"):
        service.persist(assessment(profile.profile_id, dimensions={**{key: 0 for key in DIMENSIONS}, "pricing_intent": 1}))


def test_membership_provenance_and_contributions_are_immutable(db_session):
    _, signal, profile = profile_with_signal(db_session); membership = membership_for(db_session, profile.profile_id)
    contribution = QualificationContributionInput(signal.id, "pricing_intent", "intent-pricing-v1", 50, 60, 50, 30, 30, "SELECTED")
    service = AudienceQualificationService(db_session)
    result = service.persist(assessment(profile.profile_id, selected=(membership.id,), contributions=(contribution,)))
    without_membership = service.persist(assessment(profile.profile_id))
    assert without_membership.assessment_id != result.assessment_id
    repo = AudienceQualificationRepository(db_session)
    assert repo.membership_ids(result.assessment_id) == [membership.id]
    assert len(repo.contributions(result.assessment_id)) == 1
    duplicate = (contribution, QualificationContributionInput(signal.id, "pricing_intent", "intent-pricing-v1", 50, 60, 50, 30, 30, "CAPPED"))
    with pytest.raises(AudienceQualificationContractError, match="duplicate contribution"):
        assessment(profile.profile_id, selected=(membership.id,), contributions=duplicate)
    wrong_subject = AudienceFoundationService(db_session).create_subject("PERSON")
    wrong_profile = AudienceProfileService(db_session).derive(wrong_subject.id, effective_as_of=AS_OF)
    with pytest.raises(AudienceQualificationError) as error:
        service.persist(assessment(wrong_profile.profile_id, selected=(membership.id,)))
    assert error.value.category == "INVALID_MEMBERSHIP_PROVENANCE"


def test_rollback_leaves_no_assessment_junction_or_contribution(db_session):
    subject, signal, profile = profile_with_signal(db_session)
    membership = membership_for(db_session, profile.profile_id)
    signal_id, profile_id, membership_id, subject_id = signal.id, profile.profile_id, membership.id, subject.id
    db_session.commit(); db_session.rollback()
    contribution = QualificationContributionInput(signal_id, "pricing_intent", "intent-pricing-v1", 50, 60, 50, 30, 30, "SELECTED")
    db_session.execute(text("BEGIN"))
    result = AudienceQualificationService(db_session).persist(assessment(profile_id, selected=(membership_id,), contributions=(contribution,)))
    assert db_session.get(AudienceQualificationAssessment, result.assessment_id) is not None
    assert db_session.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=result.assessment_id, membership_id=membership_id).count() == 1
    assert db_session.query(AudienceQualificationContribution).filter_by(assessment_id=result.assessment_id).count() == 1
    db_session.rollback()
    verifier = sessionmaker(bind=db_session.get_bind())()
    try:
        assert verifier.query(AudienceQualificationAssessment).filter_by(id=result.assessment_id).count() == 0
        assert verifier.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=result.assessment_id, membership_id=membership_id).count() == 0
        assert verifier.query(AudienceQualificationContribution).filter_by(assessment_id=result.assessment_id).count() == 0
        assert verifier.get(AudienceProfile, profile_id) is not None
        assert verifier.get(AudienceSegmentMembership, membership_id) is not None
        assert verifier.get(type(signal), signal_id) is not None
        assert verifier.get(type(subject), subject_id) is not None
    finally:
        verifier.close()
