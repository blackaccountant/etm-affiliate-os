"""Atomic preparation, eligibility, TOCTOU, and evidence proofs for M9B."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.crm.contracts import ContactPointStateEventInput, PermissionEventInput, SuppressionEventInput
from app.models.audience import AudienceSubject
from app.models.crm import ContactPoint, Lead
from app.models.outreach import OutreachIntent, OutreachMessage
from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.outreach.contracts import (
    OUTREACH_ELIGIBILITY_POLICY_VERSION,
    CreateOutreachIntentRequest,
    OutreachEligibilityResult,
    OutreachError,
    PreparedOutreachMessage,
)
from app.outreach.delivery_contracts import PrepareDeliveryAttemptRequest, prepared_event_fingerprint
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.outreach_delivery_attempt_service import OutreachDeliveryAttemptService
from app.services.outreach_intent_service import OutreachIntentService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


T1 = datetime(2030, 8, 30, 12, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)


def _graph_and_intent(db, suffix="one"):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contact = ContactPointService(db).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value=f"m9b-prepare-{suffix}@example.com",
    ).record
    ContactPointService(db).append_state_event(
        contact.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", T1, "m9b", f"state-{suffix}"),
    )
    PermissionService(db).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", T1, "m9b", f"permission-{suffix}"),
    )
    created = OutreachIntentService(db).create_or_reuse(CreateOutreachIntentRequest(
        lead.id, contact.id, "EMAIL", "marketing", "m9b-intent", f"intent-{suffix}",
        PreparedOutreachMessage("Frozen M9A body", "Frozen subject", "TEXT", {"locale": "en"}), T1,
    ))
    return subject, lead, contact, created


def _prepare(created, source="one", at=T1):
    return PrepareDeliveryAttemptRequest(created.intent.id, "m9b-prepare", source, at)


def test_eligible_intent_creates_exact_initial_attempt_and_prepared_evidence(db_session):
    _, lead, contact, created = _graph_and_intent(db_session, "create")
    result = OutreachDeliveryAttemptService(db_session).prepare_initial(_prepare(created))
    assert result.reused is False
    assert result.attempt.attempt_number == result.event.sequence_number == 1
    assert result.event.event_type == "PREPARED"
    assert db_session.query(OutreachDeliveryAttempt).count() == 1
    assert db_session.query(OutreachDeliveryEvent).count() == 1
    payload = result.event.safe_payload
    assert payload["eligibility"] == "ELIGIBLE"
    assert payload["contactability_state"] == "CONTACTABLE"
    assert payload["evaluated_as_of"] == T1.isoformat()
    assert payload["policy_version"] == OUTREACH_ELIGIBILITY_POLICY_VERSION
    assert payload["decision_fingerprint"] == created.intent.contactability_decision_fingerprint
    assert payload["lead_id"] == lead.id and payload["contact_point_id"] == contact.id
    assert payload["winning_state_event_id"] and payload["winning_permission_event_id"]
    assert len(result.event.event_fingerprint) == 64
    assert result.event.event_fingerprint == prepared_event_fingerprint(
        delivery_attempt_id=result.attempt.id, occurred_at=T1, safe_payload=payload,
    )


def test_prepared_payload_is_bounded_pii_safe_and_does_not_duplicate_message(db_session):
    _, _, _, created = _graph_and_intent(db_session, "pii")
    result = OutreachDeliveryAttemptService(db_session).prepare_initial(_prepare(created))
    payload_text = repr(result.event.safe_payload).lower()
    assert len(payload_text.encode()) < 8192
    assert "m9b-prepare-pii@example.com" not in payload_text
    assert "frozen m9a body" not in payload_text and "frozen subject" not in payload_text
    assert not {"subject", "body", "destination", "normalized_value", "recipient", "provider"}.intersection(
        result.event.safe_payload
    )
    assert db_session.query(OutreachMessage).count() == 1


def test_same_source_same_request_reuses_exact_attempt_before_later_revalidation(db_session):
    _, _, contact, created = _graph_and_intent(db_session, "historical")
    service = OutreachDeliveryAttemptService(db_session)
    first = service.prepare_initial(_prepare(created, "same", T1))
    PermissionService(db_session).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "OPTED_OUT", T2, "m9b", "later-optout"),
    )
    again = service.prepare_initial(_prepare(created, "same", T2))
    assert again.reused is True
    assert (again.attempt.id, again.event.id) == (first.attempt.id, first.event.id)
    assert db_session.query(OutreachDeliveryAttempt).count() == 1
    assert db_session.query(OutreachDeliveryEvent).count() == 1
    assert OutreachIntentService(db_session).revalidate_for_execution(created.intent.id, T2).state == "INELIGIBLE"


def test_same_source_different_intent_is_idempotency_conflict(db_session):
    _, _, _, first = _graph_and_intent(db_session, "conflict-one")
    _, _, _, second = _graph_and_intent(db_session, "conflict-two")
    service = OutreachDeliveryAttemptService(db_session)
    service.prepare_initial(_prepare(first, "shared"))
    with pytest.raises(OutreachError) as error:
        service.prepare_initial(_prepare(second, "shared"))
    assert error.value.category == "IDEMPOTENCY_CONFLICT"


def test_different_source_cannot_alias_attempt_one_and_gets_typed_conflict(db_session):
    _, _, _, created = _graph_and_intent(db_session, "different-source")
    service = OutreachDeliveryAttemptService(db_session)
    first = service.prepare_initial(_prepare(created, "first"))
    with pytest.raises(OutreachError) as error:
        service.prepare_initial(_prepare(created, "second"))
    assert error.value.category == "INITIAL_ATTEMPT_ALREADY_EXISTS"
    assert db_session.query(OutreachDeliveryAttempt).one().id == first.attempt.id
    assert db_session.query(OutreachDeliveryEvent).count() == 1


def test_new_prepare_revalidates_in_required_lock_order(monkeypatch, db_session):
    _, _, _, created = _graph_and_intent(db_session, "order")
    service = OutreachDeliveryAttemptService(db_session)
    calls = []

    def wrap(obj, name, label):
        original = getattr(obj, name)
        def recorded(*args, **kwargs):
            calls.append(label)
            return original(*args, **kwargs)
        monkeypatch.setattr(obj, name, recorded)

    wrap(service.attempts, "by_source", "source")
    wrap(service.eligibility, "evaluate", "revalidate")
    wrap(service.attempts, "lock_intent", "lock")
    wrap(service.attempts, "by_intent_number", "intent-number")
    service.prepare_initial(_prepare(created))
    assert calls[:5] == ["source", "revalidate", "lock", "source", "intent-number"]


def test_opt_out_after_m9a_blocks_new_preparation_with_zero_rows(db_session):
    _, _, contact, created = _graph_and_intent(db_session, "optout")
    PermissionService(db_session).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "OPTED_OUT", T2, "m9b", "optout"),
    )
    with pytest.raises(OutreachError) as error:
        OutreachDeliveryAttemptService(db_session).prepare_initial(_prepare(created, at=T2))
    assert error.value.category == "INELIGIBLE"
    assert db_session.query(OutreachDeliveryAttempt).count() == 0
    assert db_session.query(OutreachDeliveryEvent).count() == 0


def test_suppression_after_m9a_blocks_new_preparation_with_zero_rows(db_session):
    _, lead, contact, created = _graph_and_intent(db_session, "suppression")
    SuppressionService(db_session).append(lead.id, SuppressionEventInput(
        "CONTACT_POINT_CHANNEL", "APPLIED", "MANUAL", T2, "m9b", "suppression",
        contact_point_id=contact.id, channel="EMAIL",
    ))
    with pytest.raises(OutreachError) as error:
        OutreachDeliveryAttemptService(db_session).prepare_initial(_prepare(created, at=T2))
    assert error.value.category == "INELIGIBLE"
    assert db_session.query(OutreachDeliveryAttempt).count() == 0
    assert db_session.query(OutreachDeliveryEvent).count() == 0


def test_policy_unavailable_creates_zero_attempts_and_events(monkeypatch, db_session):
    _, _, _, created = _graph_and_intent(db_session, "unavailable")
    service = OutreachDeliveryAttemptService(db_session)
    unavailable = OutreachEligibilityResult(
        "POLICY_UNAVAILABLE", ("CONTACTABILITY_UNAVAILABLE",), OUTREACH_ELIGIBILITY_POLICY_VERSION,
        "a" * 64, T2, None,
    )
    monkeypatch.setattr(service.eligibility, "evaluate", lambda **_kwargs: (unavailable, None))
    with pytest.raises(OutreachError) as error:
        service.prepare_initial(_prepare(created, at=T2))
    assert error.value.category == "POLICY_UNAVAILABLE"
    assert db_session.query(OutreachDeliveryAttempt).count() == 0
    assert db_session.query(OutreachDeliveryEvent).count() == 0


def test_attempt_and_prepared_event_rollback_atomically_preserves_frozen_prerequisites(db_session, db_session_factory):
    subject, lead, contact, created = _graph_and_intent(db_session, "rollback")
    prerequisite_ids = subject.id, lead.id, contact.id, created.intent.id, created.message.id
    db_session.commit()
    db_session.execute(text("BEGIN"))
    result = OutreachDeliveryAttemptService(db_session).prepare_initial(_prepare(created))
    attempt_id, event_id = result.attempt.id, result.event.id
    assert db_session.in_transaction()
    db_session.rollback()
    verifier = db_session_factory()
    try:
        assert verifier.get(OutreachDeliveryAttempt, attempt_id) is None
        assert verifier.get(OutreachDeliveryEvent, event_id) is None
        assert verifier.get(AudienceSubject, prerequisite_ids[0]) is not None
        assert verifier.get(Lead, prerequisite_ids[1]) is not None
        assert verifier.get(ContactPoint, prerequisite_ids[2]) is not None
        assert verifier.get(OutreachIntent, prerequisite_ids[3]) is not None
        assert verifier.get(OutreachMessage, prerequisite_ids[4]) is not None
    finally:
        verifier.close()


def test_preparation_uses_caller_session_without_transaction_boundaries(monkeypatch, db_session):
    _, _, _, created = _graph_and_intent(db_session, "transaction")
    service = OutreachDeliveryAttemptService(db_session)
    assert service.db is db_session
    assert service.attempts.db is service.events.db is service.messages.db is db_session

    calls = {name: 0 for name in ("begin", "begin_nested", "commit", "rollback")}

    def forbidden(name):
        def record(*_args, **_kwargs):
            calls[name] += 1
            raise AssertionError(f"M9B production called Session.{name}")
        return record

    for name in calls:
        monkeypatch.setattr(db_session, name, forbidden(name))

    service.prepare_initial(_prepare(created))
    assert calls == {"begin": 0, "begin_nested": 0, "commit": 0, "rollback": 0}
    assert db_session.in_transaction()
    assert "M9C must revalidate before any send" in OutreachDeliveryAttemptService.__doc__
