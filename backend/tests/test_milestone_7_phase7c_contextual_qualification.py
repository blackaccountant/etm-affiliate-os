from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.audience.contextual_qualification import qualify_contextually
from app.audience.contextual_qualification_contracts import ContextualQualificationError, ContextualQualificationInput
from app.audience.intent_scoring import score_intent
from app.audience.intent_scoring_contracts import IntentScoringInput, IntentScoringResult, SCORING_DIMENSIONS
from app.audience.profile_contracts import AudienceProfileSummaryFact
from app.audience.qualification_contracts import DIMENSIONS, QualificationContext, QualificationRuleset
from app.models.audience import AudienceProfile, AudienceQualificationAssessment, AudienceQualificationAssessmentMembership, AudienceQualificationContribution, AudienceSegment, AudienceSegmentMembership, AudienceSegmentRevision
from app.repositories.audience_qualification_repository import AudienceQualificationRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_profile_service import AudienceProfileService
from app.services.audience_qualification_evaluation_service import AudienceQualificationEvaluationService
from app.services.audience_segment_membership_service import AudienceSegmentMembershipError, AudienceSegmentMembershipService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)

def ruleset(*, gates=(), weights=None, cap=100):
    intent = {key: 0 for key in DIMENSIONS}; intent["purchase_request_intent"] = 100
    qualification = weights or {key: (100 if key == "business_need_fit" else 0) for key in DIMENSIONS}
    return QualificationRuleset("m7c-v1", {"PROBLEM": ("problem_strength",), "INTEREST": ("interest_alignment",), "INTENT": ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent"), "PURCHASE": ("purchase_signal",), "ENGAGEMENT": ("engagement",), "BUSINESS_NEED": ("business_need_fit",)}, {"RESEARCH": 20,"COMPARE":40,"EVALUATE":60,"PRICING":80,"PURCHASE_REQUEST":100}, "MULTIPLY_CONFIDENCE_CAP", {**{key:100 for key in DIMENSIONS}, "business_need_fit":cap}, intent, qualification, {"NOT_QUALIFIED":0,"EARLY":40,"QUALIFIED":60,"HIGH_INTENT":80}, tuple(gates))

def fact(signal_id, topic="hosting", strength=50, confidence=60): return AudienceProfileSummaryFact(signal_id, "BUSINESS_NEED", topic, topic.title(), strength, confidence, NOW)
def scoring(): return IntentScoringResult({key:0 for key in SCORING_DIMENSIONS}, 0, ())
def run(*facts, subject="ORGANIZATION", context=None, value_ruleset=None, memberships=(), m7b=None): return qualify_contextually(ContextualQualificationInput(m7b or scoring(), tuple(facts), subject, context or QualificationContext("NONE"), value_ruleset or ruleset(), tuple(memberships)))

def test_context_modes_business_need_arithmetic_duplicates_and_cap():
    assert run(fact("a")).business_need_fit == 0
    assert run(fact("a"), context=QualificationContext("TOPIC", topic="hosting")).business_need_fit == 30
    assert run(fact("a", "email"), context=QualificationContext("TOPIC", topic="hosting")).business_need_fit == 0
    assert run(fact("a"), subject="PERSON", context=QualificationContext("TOPIC", topic="hosting")).business_need_fit == 0
    assert run(fact("a", strength=100, confidence=100), fact("b", strength=50, confidence=100), context=QualificationContext("PRODUCT", context_id="p", topic="hosting"), value_ruleset=ruleset(cap=60)).business_need_fit == 60
    value = run(fact("b"), fact("a"), context=QualificationContext("OFFER", context_id="o", topic="hosting"))
    assert [item.source_signal_id for item in value.contributions if item.disposition == "SELECTED"] == ["a"] and any(item.disposition == "DUPLICATE_SUPPRESSED" for item in value.contributions)

def test_gates_scores_status_and_integrity():
    gated = ruleset(gates=("r1",)); passed = run(context=QualificationContext("NONE"), value_ruleset=gated, memberships=(("r1", True),))
    assert passed.gate_passed and passed.qualification_status == "NOT_QUALIFIED"
    failed = run(fact("a", strength=100, confidence=100), context=QualificationContext("TOPIC", topic="hosting"), value_ruleset=gated, memberships=(("r1", False),))
    assert not failed.gate_passed and failed.qualification_score == 100 and failed.qualification_status == "NOT_QUALIFIED"
    bad = {key:0 for key in DIMENSIONS}; bad["business_need_fit"] = 99
    with pytest.raises(ContextualQualificationError): run(value_ruleset=ruleset(weights=bad))


@pytest.mark.parametrize(("score", "status"), [(0, "NOT_QUALIFIED"), (39, "NOT_QUALIFIED"), (40, "EARLY"), (59, "EARLY"), (60, "QUALIFIED"), (79, "QUALIFIED"), (80, "HIGH_INTENT"), (100, "HIGH_INTENT")])
def test_qualification_boundaries_preserve_m7b_result(score, status):
    dimensions = {key: 0 for key in SCORING_DIMENSIONS}; dimensions["purchase_request_intent"] = score
    source = IntentScoringResult(dimensions, score, ())
    weights = {key: (100 if key == "purchase_request_intent" else 0) for key in DIMENSIONS}
    result = run(context=QualificationContext("NONE"), value_ruleset=ruleset(weights=weights), m7b=source)
    assert result.qualification_score == score and result.qualification_status == status
    assert source.dimensions == dimensions and source.intent_score == score and result.business_need_fit == 0


def test_required_memberships_are_explicit_and_add_no_score():
    gated = ruleset(gates=("required",))
    context = QualificationContext("TOPIC", topic="hosting")
    assert not run(fact("a", strength=100, confidence=100), context=context, value_ruleset=gated).gate_passed
    assert not run(fact("a", strength=100, confidence=100), context=context, value_ruleset=gated, memberships=(("other", True),)).gate_passed
    assert not run(fact("a", strength=100, confidence=100), context=context, value_ruleset=gated, memberships=(("required", False),)).gate_passed
    passed = run(fact("a", strength=100, confidence=100), context=context, value_ruleset=gated, memberships=(("required", True),))
    assert passed.gate_passed and passed.qualification_score == 100


def test_service_uses_immutable_profile_and_persists_once_with_membership_provenance(db_session):
    foundation = AudienceFoundationService(db_session)
    subject = foundation.create_subject("ORGANIZATION")
    observation = foundation.ingest_observation(
        research_run_id=None, subject_id=subject.id, source_namespace="m7c", source_type="MANUAL",
        external_observation_id="m7c-business", source_reference="m7c", observed_at=NOW,
        normalized_fact={"tag": "m7c-business"},
    )
    evidence = foundation.record_evidence(
        observation_id=observation.id, source_reference="m7c",
        normalized_representation={"tag": "m7c-business"}, content_fingerprint="c" * 64,
    )
    AudienceSignalService(db_session).persist(
        SignalCandidate("BUSINESS_NEED", "hosting", "Hosting", None, 50, 60, [evidence.id], "m7c-v1"),
        subject_id=subject.id,
    )
    intent_signal = AudienceSignalService(db_session).persist(
        SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "m7c-v1"),
        subject_id=subject.id,
    )
    profile = AudienceProfileService(db_session).derive(subject.id, effective_as_of=NOW)
    segment = AudienceSegment(segment_key="m7c-required", name="M7C required")
    db_session.add(segment); db_session.flush()
    revision = AudienceSegmentRevision(
        segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1",
        definition_fingerprint="d" * 64,
        definition_json={"all_of": [{"signal_type": "BUSINESS_NEED", "topic": "hosting", "intent_stage": None,
                                      "minimum_strength": None, "minimum_confidence": None, "max_age_days": None}],
                         "allowed_subject_types": ["ORGANIZATION"]},
    )
    db_session.add(revision); db_session.flush()
    membership = AudienceSegmentMembership(segment_revision_id=revision.id, profile_id=profile.profile_id, is_member=True)
    second_revision = AudienceSegmentRevision(
        segment_id=segment.id, revision_number=2, segment_ruleset_version="audience-segment-v1",
        definition_fingerprint="e" * 64, definition_json=revision.definition_json,
    )
    db_session.add_all((membership, second_revision)); db_session.flush()
    second_membership = AudienceSegmentMembership(segment_revision_id=second_revision.id, profile_id=profile.profile_id, is_member=False)
    db_session.add(second_membership); db_session.flush()

    value_ruleset = ruleset(gates=(revision.id,))
    service = AudienceQualificationEvaluationService(db_session)
    first = service.evaluate(profile.profile_id, value_ruleset, QualificationContext("TOPIC", topic="hosting"), (membership.id,))
    again = service.evaluate(profile.profile_id, value_ruleset, QualificationContext("TOPIC", topic="hosting"), (membership.id,))
    changed_context = service.evaluate(profile.profile_id, value_ruleset, QualificationContext("PRODUCT", context_id="product-1", topic="hosting"), (membership.id,))
    changed_memberships = service.evaluate(profile.profile_id, value_ruleset, QualificationContext("TOPIC", topic="hosting"), (membership.id, second_membership.id))

    assert first.assessment_id == again.assessment_id and again.reused
    assert changed_context.assessment_id != first.assessment_id
    assert changed_memberships.assessment_id != first.assessment_id
    repository = AudienceQualificationRepository(db_session)
    assert repository.membership_ids(first.assessment_id) == [membership.id]
    contributions = repository.contributions(first.assessment_id)
    profile_row = db_session.get(AudienceProfile, profile.profile_id)
    expected_m7b = score_intent(IntentScoringInput(AudienceSegmentMembershipService(db_session)._facts(profile_row), profile_row.effective_as_of, value_ruleset))
    contribution_fields = lambda item: (item.source_signal_id, item.dimension, item.rule_id, item.strength, item.confidence, item.raw_amount, item.confidence_adjusted_amount, item.final_amount, item.disposition)
    assert {contribution_fields(item) for item in contributions if item.dimension != "business_need_fit"} == {contribution_fields(item) for item in expected_m7b.contributions}
    assert {(item.dimension, item.final_amount) for item in contributions if item.dimension == "business_need_fit"} == {("business_need_fit", 30)}
    assert db_session.in_transaction()

    db_session.commit(); db_session.rollback()
    db_session.execute(text("BEGIN"))
    transient = service.evaluate(profile.profile_id, value_ruleset, QualificationContext("OFFER", context_id="offer-1", topic="hosting"), (membership.id,))
    assert db_session.get(AudienceQualificationAssessment, transient.assessment_id) is not None
    assert db_session.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=transient.assessment_id).count() == 1
    assert db_session.query(AudienceQualificationContribution).filter_by(assessment_id=transient.assessment_id).count() == 2
    db_session.rollback()
    verifier = sessionmaker(bind=db_session.get_bind())()
    try:
        assert verifier.query(AudienceQualificationAssessment).filter_by(id=transient.assessment_id).count() == 0
        assert verifier.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=transient.assessment_id).count() == 0
        assert verifier.query(AudienceQualificationContribution).filter_by(assessment_id=transient.assessment_id).count() == 0
        assert verifier.get(AudienceProfile, profile.profile_id) is not None
        assert verifier.get(AudienceSegmentMembership, membership.id) is not None
        assert verifier.get(type(intent_signal), intent_signal.id) is not None
    finally:
        verifier.close()


def test_service_rejects_wrong_profile_membership_without_persistence(db_session):
    foundation = AudienceFoundationService(db_session)
    profile_a_subject = foundation.create_subject("ORGANIZATION")
    profile_b_subject = foundation.create_subject("ORGANIZATION")
    profile_a = AudienceProfileService(db_session).derive(profile_a_subject.id, effective_as_of=NOW)
    profile_b = AudienceProfileService(db_session).derive(profile_b_subject.id, effective_as_of=NOW)
    segment = AudienceSegment(segment_key="m7c-wrong-profile", name="M7C wrong profile")
    db_session.add(segment); db_session.flush()
    revision = AudienceSegmentRevision(segment_id=segment.id, revision_number=1, segment_ruleset_version="audience-segment-v1", definition_fingerprint="f" * 64, definition_json={"all_of": [{"signal_type": "PROBLEM", "topic": None, "intent_stage": None, "minimum_strength": None, "minimum_confidence": None, "max_age_days": None}], "allowed_subject_types": []})
    db_session.add(revision); db_session.flush()
    wrong_membership = AudienceSegmentMembership(segment_revision_id=revision.id, profile_id=profile_b.profile_id, is_member=True)
    db_session.add(wrong_membership); db_session.flush()
    with pytest.raises(ValueError, match="invalid membership provenance"):
        AudienceQualificationEvaluationService(db_session).evaluate(profile_a.profile_id, ruleset(), QualificationContext("NONE"), (wrong_membership.id,))
    assert db_session.query(AudienceQualificationAssessment).count() == 0
    assert db_session.query(AudienceQualificationAssessmentMembership).count() == 0
    assert db_session.query(AudienceQualificationContribution).count() == 0


def test_service_rejects_profile_summary_source_junction_mismatch_without_repair(db_session):
    subject = AudienceFoundationService(db_session).create_subject("ORGANIZATION")
    profile = AudienceProfileService(db_session).derive(subject.id, effective_as_of=NOW)
    stored = db_session.get(AudienceProfile, profile.profile_id)
    summary = dict(stored.summary_json)
    categories = {key: list(value) for key, value in summary["categories"].items()}
    categories.setdefault("BUSINESS_NEED", []).append(fact("missing-signal").to_dict())
    summary["categories"] = categories
    stored.summary_json = summary
    db_session.flush()
    with pytest.raises(AudienceSegmentMembershipError) as error:
        AudienceQualificationEvaluationService(db_session).evaluate(profile.profile_id, ruleset(), QualificationContext("NONE"))
    assert error.value.category == "MALFORMED_PROFILE_SUMMARY"
    assert db_session.query(AudienceQualificationAssessment).count() == 0
    assert db_session.query(AudienceQualificationAssessmentMembership).count() == 0
    assert db_session.query(AudienceQualificationContribution).count() == 0
