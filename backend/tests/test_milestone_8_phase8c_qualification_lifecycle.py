"""Focused M8C proofs for exact qualification links and Lead lifecycle history."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.crm.contracts import CRMError, PermissionEventInput, SuppressionEventInput
from app.crm.lifecycle_contracts import LifecycleTransitionRequest
from app.models.audience import AudienceProfile, AudienceQualificationAssessment, AudienceSubject
from app.models.crm import ContactPoint, Lead, PermissionEvent, SuppressionEvent
from app.models.crm_relationships import LeadLifecycleEvent, LeadQualificationLink
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_lifecycle_service import LeadLifecycleService
from app.services.lead_qualification_link_service import LeadQualificationLinkService
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
DIMENSIONS = (
    "problem_strength", "interest_alignment", "research_intent", "comparison_intent",
    "evaluation_intent", "pricing_intent", "purchase_request_intent", "purchase_signal",
    "engagement", "business_need_fit",
)


def _assessment(db, subject_id: str, status: str = "QUALIFIED"):
    token = uuid4().hex
    profile = AudienceProfile(
        subject_id=subject_id,
        profile_ruleset_version=f"m8c-profile-{token}",
        source_fingerprint=(token * 2)[:64],
        effective_as_of=NOW,
        summary_json={"m8c": True},
    )
    db.add(profile)
    db.flush()
    score = {"NOT_QUALIFIED": 0, "EARLY": 40, "QUALIFIED": 60, "HIGH_INTENT": 80}[status]
    value = AudienceQualificationAssessment(
        profile_id=profile.id,
        scoring_ruleset_version=f"m8c-scoring-{token}",
        scoring_ruleset_fingerprint=("a" + token * 2)[:64],
        scoring_ruleset_json={"version": token},
        context_type="NONE",
        context_json={},
        context_fingerprint=("b" + token * 2)[:64],
        selected_membership_fingerprint=("c" + token * 2)[:64],
        intent_score=score,
        qualification_score=score,
        qualification_status=status,
        derived_at=NOW,
        **{field: score for field in DIMENSIONS},
    )
    db.add(value)
    db.flush()
    return profile, value


def _lead_with_assessment(db, subject_type="PERSON", status="QUALIFIED"):
    subject = AudienceFoundationService(db).create_subject(subject_type)
    lead = LeadService(db).create_or_reuse(subject.id).record
    profile, assessment = _assessment(db, subject.id, status)
    return subject, lead, profile, assessment


def _request(state, key, seconds=0, occurred_at=None):
    return LifecycleTransitionRequest(
        state,
        occurred_at or NOW + timedelta(seconds=seconds),
        "m8c-test",
        key,
    )


def _initialize_and_enrich(db, lead, prefix="flow"):
    service = LeadLifecycleService(db)
    service.transition(lead.id, _request("DISCOVERED", f"{prefix}-discovered", 0))
    service.transition(lead.id, _request("ENRICHED", f"{prefix}-enriched", 1))
    return service


@pytest.mark.parametrize("subject_type", ["PERSON", "ORGANIZATION", "ANONYMOUS"])
def test_exact_subject_qualification_linking_supports_all_frozen_subject_types(db_session, subject_type):
    _, lead, _, assessment = _lead_with_assessment(db_session, subject_type)
    result = LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    assert result.reused is False
    link = db_session.get(LeadQualificationLink, result.link_id)
    assert (link.lead_id, link.assessment_id) == (lead.id, assessment.id)
    assert db_session.in_transaction()
    if subject_type == "ANONYMOUS":
        with pytest.raises(CRMError) as error:
            ContactPointService(db_session).create_or_reuse(
                lead.id, kind="EMAIL", normalized_value="anonymous@example.com"
            )
        assert error.value.category == "ANONYMOUS_CONTACT_FORBIDDEN"


def test_subjectless_and_mismatched_leads_are_rejected(db_session):
    subjectless = LeadService(db_session).create_or_reuse(None).record
    _, _, _, assessment = _lead_with_assessment(db_session)
    service = LeadQualificationLinkService(db_session)
    with pytest.raises(CRMError) as required:
        service.link(subjectless.id, assessment.id)
    assert required.value.category == "LEAD_SUBJECT_REQUIRED"

    other_subject = AudienceFoundationService(db_session).create_subject("ORGANIZATION")
    other_lead = LeadService(db_session).create_or_reuse(other_subject.id).record
    with pytest.raises(CRMError) as mismatch:
        service.link(other_lead.id, assessment.id)
    assert mismatch.value.category == "QUALIFICATION_SUBJECT_MISMATCH"
    assert db_session.query(LeadQualificationLink).count() == 0


def test_link_retry_reuses_pair_and_multiple_assessments_form_history(db_session):
    subject, lead, _, first_assessment = _lead_with_assessment(db_session)
    _, second_assessment = _assessment(db_session, subject.id, "HIGH_INTENT")
    service = LeadQualificationLinkService(db_session)
    first = service.link(lead.id, first_assessment.id)
    again = service.link(lead.id, first_assessment.id)
    second = service.link(lead.id, second_assessment.id)
    assert first.reused is False and again.reused is True and second.reused is False
    assert first.link_id == again.link_id
    assert db_session.query(LeadQualificationLink).filter_by(lead_id=lead.id).count() == 2


def test_link_does_not_copy_or_mutate_frozen_assessment_content(db_session):
    _, lead, _, assessment = _lead_with_assessment(db_session, status="HIGH_INTENT")
    before = (assessment.intent_score, assessment.qualification_score, assessment.qualification_status)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    db_session.refresh(assessment)
    assert (assessment.intent_score, assessment.qualification_score, assessment.qualification_status) == before
    assert set(Lead.__table__.columns.keys()) == {"id", "subject_id", "created_at"}
    assert "current_assessment_id" not in Lead.__table__.columns
    assert "lifecycle_status" not in Lead.__table__.columns


def test_initialization_is_explicit_idempotent_and_caller_owned(db_session):
    _, lead, _, _ = _lead_with_assessment(db_session)
    service = LeadLifecycleService(db_session)
    request = _request("DISCOVERED", "initial")
    first = service.transition(lead.id, request)
    again = service.transition(lead.id, request)
    assert first.reused is False and again.reused is True
    assert first.event_id == again.event_id and first.sequence_number == 1
    assert service.effective_state(lead.id) == "DISCOVERED"
    assert db_session.in_transaction()


def test_complete_forward_graph_has_monotonic_sequence_and_terminal_archive(db_session):
    _, lead, _, assessment = _lead_with_assessment(db_session)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    service = LeadLifecycleService(db_session)
    for index, state in enumerate(
        ("DISCOVERED", "ENRICHED", "QUALIFIED", "READY_FOR_REVIEW", "ARCHIVED")
    ):
        service.transition(lead.id, _request(state, f"forward-{index}", index))
    events = db_session.query(LeadLifecycleEvent).filter_by(lead_id=lead.id).order_by(
        LeadLifecycleEvent.sequence_number
    ).all()
    assert [event.sequence_number for event in events] == [1, 2, 3, 4, 5]
    assert [(event.from_state, event.to_state) for event in events] == [
        (None, "DISCOVERED"),
        ("DISCOVERED", "ENRICHED"),
        ("ENRICHED", "QUALIFIED"),
        ("QUALIFIED", "READY_FOR_REVIEW"),
        ("READY_FOR_REVIEW", "ARCHIVED"),
    ]
    with pytest.raises(CRMError) as terminal:
        service.transition(lead.id, _request("DISCOVERED", "reactivate", 6))
    assert terminal.value.category == "INVALID_LIFECYCLE_TRANSITION"


def test_direct_archive_paths_are_allowed(db_session):
    _, discovered_lead, _, _ = _lead_with_assessment(db_session)
    discovered = LeadLifecycleService(db_session)
    discovered.transition(discovered_lead.id, _request("DISCOVERED", "d-init"))
    discovered.transition(discovered_lead.id, _request("ARCHIVED", "d-archive", 1))
    assert discovered.effective_state(discovered_lead.id) == "ARCHIVED"

    _, enriched_lead, _, _ = _lead_with_assessment(db_session, "ORGANIZATION")
    enriched = _initialize_and_enrich(db_session, enriched_lead, "e")
    enriched.transition(enriched_lead.id, _request("ARCHIVED", "e-archive", 2))
    assert enriched.effective_state(enriched_lead.id) == "ARCHIVED"


@pytest.mark.parametrize(
    "prepare,target",
    [
        (("DISCOVERED",), "QUALIFIED"),
        (("DISCOVERED",), "READY_FOR_REVIEW"),
        (("DISCOVERED", "ENRICHED"), "READY_FOR_REVIEW"),
        (("DISCOVERED", "ENRICHED"), "DISCOVERED"),
    ],
)
def test_skips_and_backwards_transitions_are_rejected(db_session, prepare, target):
    _, lead, _, assessment = _lead_with_assessment(db_session)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    service = LeadLifecycleService(db_session)
    for index, state in enumerate(prepare):
        service.transition(lead.id, _request(state, f"prepare-{target}-{index}", index))
    with pytest.raises(CRMError) as error:
        service.transition(lead.id, _request(target, f"invalid-{target}", len(prepare)))
    assert error.value.category == "INVALID_LIFECYCLE_TRANSITION"


@pytest.mark.parametrize(
    "status,allowed",
    [("NOT_QUALIFIED", False), ("EARLY", False), ("QUALIFIED", True), ("HIGH_INTENT", True)],
)
def test_qualified_gate_uses_only_frozen_linked_assessment_status(db_session, status, allowed):
    _, lead, _, assessment = _lead_with_assessment(db_session, status=status)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    service = _initialize_and_enrich(db_session, lead, status.lower())
    if allowed:
        result = service.transition(lead.id, _request("QUALIFIED", f"{status}-qualified", 2))
        assert result.effective_state == "QUALIFIED"
    else:
        with pytest.raises(CRMError) as error:
            service.transition(lead.id, _request("QUALIFIED", f"{status}-qualified", 2))
        assert error.value.category == "QUALIFYING_ASSESSMENT_REQUIRED"


def test_qualified_gate_requires_link_and_accepts_any_historical_qualifying_link(db_session):
    subject, lead, _, early = _lead_with_assessment(db_session, status="EARLY")
    _, qualified = _assessment(db_session, subject.id, "QUALIFIED")
    service = _initialize_and_enrich(db_session, lead, "history")
    with pytest.raises(CRMError) as missing:
        service.transition(lead.id, _request("QUALIFIED", "history-missing", 2))
    assert missing.value.category == "QUALIFYING_ASSESSMENT_REQUIRED"
    links = LeadQualificationLinkService(db_session)
    links.link(lead.id, early.id)
    with pytest.raises(CRMError):
        service.transition(lead.id, _request("QUALIFIED", "history-early", 2))
    links.link(lead.id, qualified.id)
    assert service.transition(
        lead.id, _request("QUALIFIED", "history-qualified", 2)
    ).effective_state == "QUALIFIED"


def test_ready_for_review_is_independent_of_permission_and_suppression(db_session):
    _, lead, _, assessment = _lead_with_assessment(db_session)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    contact = ContactPointService(db_session).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value="review@example.com"
    ).record
    PermissionService(db_session).append(
        contact.id,
        PermissionEventInput("EMAIL", "marketing", "OPTED_OUT", NOW, "m8c-test", "opt-out"),
    )
    SuppressionService(db_session).append(
        lead.id,
        SuppressionEventInput(
            "GLOBAL_LEAD", "APPLIED", "MANUAL", NOW, "m8c-test", "suppressed"
        ),
    )
    service = _initialize_and_enrich(db_session, lead, "review")
    service.transition(lead.id, _request("QUALIFIED", "review-qualified", 2))
    result = service.transition(lead.id, _request("READY_FOR_REVIEW", "review-ready", 3))
    assert result.effective_state == "READY_FOR_REVIEW"
    assert db_session.query(PermissionEvent).count() == 1
    assert db_session.query(SuppressionEvent).count() == 1


def test_lifecycle_retry_reuses_and_conflicting_same_source_key_is_typed(db_session):
    _, lead, _, _ = _lead_with_assessment(db_session)
    service = LeadLifecycleService(db_session)
    request = _request("DISCOVERED", "same-key")
    first = service.transition(lead.id, request)
    again = service.transition(lead.id, request)
    assert first.event_id == again.event_id and again.reused is True
    with pytest.raises(CRMError) as conflict:
        service.transition(lead.id, _request("DISCOVERED", "same-key", 1))
    assert conflict.value.category == "IDEMPOTENCY_CONFLICT"
    assert db_session.query(LeadLifecycleEvent).count() == 1


def test_backdated_rejected_equal_timestamp_allowed_and_sequence_is_authoritative(db_session):
    _, lead, _, _ = _lead_with_assessment(db_session)
    service = LeadLifecycleService(db_session)
    service.transition(lead.id, _request("DISCOVERED", "time-1", occurred_at=NOW))
    service.transition(lead.id, _request("ENRICHED", "time-2", occurred_at=NOW))
    events = service.lifecycle.list_ordered(lead.id)
    assert [(event.occurred_at, event.sequence_number) for event in events] == [(NOW, 1), (NOW, 2)]
    with pytest.raises(CRMError) as backdated:
        service.transition(
            lead.id,
            _request("ARCHIVED", "time-backdated", occurred_at=NOW - timedelta(microseconds=1)),
        )
    assert backdated.value.category == "BACKDATED_LIFECYCLE_EVENT"


def test_m8c_has_no_network_provider_signal_scoring_or_contactability_coupling(monkeypatch, db_session):
    def fail(*_args, **_kwargs):
        raise AssertionError("external or forbidden boundary accessed")

    monkeypatch.setattr("socket.create_connection", fail)
    _, lead, _, assessment = _lead_with_assessment(db_session)
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    LeadLifecycleService(db_session).transition(lead.id, _request("DISCOVERED", "offline"))
    assert db_session.query(LeadQualificationLink).count() == 1
    assert db_session.query(LeadLifecycleEvent).count() == 1


def test_non_empty_m8c_graph_is_fully_removed_by_caller_rollback(db_session, db_session_factory):
    subject, lead, profile, assessment = _lead_with_assessment(db_session)
    ids = (subject.id, lead.id, profile.id, assessment.id)
    db_session.commit()
    db_session.execute(text("BEGIN"))
    LeadQualificationLinkService(db_session).link(lead.id, assessment.id)
    lifecycle = LeadLifecycleService(db_session)
    lifecycle.transition(lead.id, _request("DISCOVERED", "rollback-discovered"))
    lifecycle.transition(lead.id, _request("ENRICHED", "rollback-enriched", 1))
    assert db_session.query(LeadQualificationLink).count() == 1
    assert db_session.query(LeadLifecycleEvent).count() == 2
    db_session.rollback()

    verifier = db_session_factory()
    try:
        assert verifier.query(LeadQualificationLink).count() == 0
        assert verifier.query(LeadLifecycleEvent).count() == 0
        assert verifier.get(AudienceSubject, ids[0]) is not None
        assert verifier.get(Lead, ids[1]) is not None
        assert verifier.get(AudienceProfile, ids[2]) is not None
        assert verifier.get(AudienceQualificationAssessment, ids[3]) is not None
        assert verifier.query(ContactPoint).count() == 0
    finally:
        verifier.close()
