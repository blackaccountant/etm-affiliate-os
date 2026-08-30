"""Persistence, identity, immutability, and boundary proofs for M9B."""

from datetime import datetime, timedelta, timezone
import inspect

import pytest

from app.crm.contracts import ContactPointStateEventInput, PermissionEventInput
from app.models.outreach_delivery import OutreachDeliveryAttempt, OutreachDeliveryEvent
from app.outreach.contracts import CreateOutreachIntentRequest, OutreachError, PreparedOutreachMessage
from app.outreach.delivery_contracts import (
    DeliveryEventType,
    PrepareDeliveryAttemptRequest,
    prepared_event_fingerprint,
    prepared_event_source_identity,
)
from app.repositories.outreach_delivery_attempt_repository import OutreachDeliveryAttemptRepository
from app.repositories.outreach_delivery_event_repository import OutreachDeliveryEventRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.outreach_delivery_attempt_service import OutreachDeliveryAttemptService
from app.services.outreach_intent_service import OutreachIntentService
from app.services.permission_service import PermissionService


NOW = datetime(2030, 8, 30, 12, tzinfo=timezone.utc)


def _intent(db, suffix="one"):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contact = ContactPointService(db).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value=f"m9b-{suffix}@example.com",
    ).record
    ContactPointService(db).append_state_event(
        contact.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW, "m9b", f"state-{suffix}"),
    )
    PermissionService(db).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", NOW, "m9b", f"permission-{suffix}"),
    )
    created = OutreachIntentService(db).create_or_reuse(CreateOutreachIntentRequest(
        lead.id, contact.id, "EMAIL", "marketing", "m9b-intent", f"intent-{suffix}",
        PreparedOutreachMessage("Immutable prepared body", "Subject", "TEXT", {"locale": "en"}), NOW,
    ))
    return lead, contact, created


def _request(intent, source="one", at=NOW):
    return PrepareDeliveryAttemptRequest(intent.id, "m9b-delivery", source, at)


def test_request_identity_is_only_intent_and_excludes_time_and_provider_facts(db_session):
    _, _, created = _intent(db_session, "fingerprint")
    first = _request(created.intent, at=NOW)
    later = _request(created.intent, at=NOW + timedelta(days=1))
    assert first.request_fingerprint == later.request_fingerprint
    assert set(PrepareDeliveryAttemptRequest.__dataclass_fields__) == {
        "outreach_intent_id", "source_namespace", "source_event_key", "evaluated_as_of",
    }
    assert not {"provider", "destination", "message_id", "recipient"}.intersection(
        PrepareDeliveryAttemptRequest.__dataclass_fields__
    )


def test_attempt_schema_is_immutable_identity_without_status_message_or_provider_fields():
    columns = set(OutreachDeliveryAttempt.__table__.columns.keys())
    assert columns == {
        "id", "outreach_intent_id", "attempt_number", "source_namespace",
        "source_event_key", "request_fingerprint", "created_at",
    }
    assert not {
        "status", "subject", "body", "normalized_value", "destination", "recipient_email",
        "provider", "provider_id", "provider_message_id", "provider_secret",
    }.intersection(columns)
    uniques = {
        tuple(constraint.columns.keys())
        for constraint in OutreachDeliveryAttempt.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("source_namespace", "source_event_key") in uniques
    assert ("outreach_intent_id", "attempt_number") in uniques
    checks = {
        str(constraint.sqltext)
        for constraint in OutreachDeliveryAttempt.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "attempt_number >= 1" in checks
    assert "attempt_number = 1" not in checks
    assert not hasattr(OutreachDeliveryAttemptRepository, "update")
    assert not hasattr(OutreachDeliveryAttemptRepository, "delete")


def test_attempt_repository_reuses_same_source_and_types_both_conflicts(db_session):
    _, _, first_intent = _intent(db_session, "attempt-one")
    _, _, second_intent = _intent(db_session, "attempt-two")
    repository = OutreachDeliveryAttemptRepository(db_session)
    original = OutreachDeliveryAttempt(
        outreach_intent_id=first_intent.intent.id, attempt_number=1,
        source_namespace="source", source_event_key="same", request_fingerprint="a" * 64,
    )
    assert repository.create_initial_or_reuse(original).reused is False
    same = OutreachDeliveryAttempt(
        outreach_intent_id=first_intent.intent.id, attempt_number=1,
        source_namespace="source", source_event_key="same", request_fingerprint="a" * 64,
    )
    assert repository.create_initial_or_reuse(same).record.id == original.id
    conflicting_request = OutreachDeliveryAttempt(
        outreach_intent_id=second_intent.intent.id, attempt_number=1,
        source_namespace="source", source_event_key="same", request_fingerprint="b" * 64,
    )
    with pytest.raises(OutreachError, match="immutable content") as error:
        repository.create_initial_or_reuse(conflicting_request)
    assert error.value.category == "IDEMPOTENCY_CONFLICT"
    different_source = OutreachDeliveryAttempt(
        outreach_intent_id=first_intent.intent.id, attempt_number=1,
        source_namespace="source", source_event_key="different", request_fingerprint="a" * 64,
    )
    with pytest.raises(OutreachError) as error:
        repository.create_initial_or_reuse(different_source)
    assert error.value.category == "INITIAL_ATTEMPT_ALREADY_EXISTS"


def test_initial_repository_rejects_attempt_two_before_flush_and_attempt_one_still_works(db_session):
    _, _, created = _intent(db_session, "initial-boundary")
    repository = OutreachDeliveryAttemptRepository(db_session)
    forbidden = OutreachDeliveryAttempt(
        outreach_intent_id=created.intent.id, attempt_number=2,
        source_namespace="source", source_event_key="attempt-two", request_fingerprint="a" * 64,
    )
    with pytest.raises(OutreachError) as error:
        repository.create_initial_or_reuse(forbidden)
    assert error.value.category == "INVALID_INITIAL_ATTEMPT_NUMBER"
    assert db_session.query(OutreachDeliveryAttempt).count() == 0
    assert db_session.query(OutreachDeliveryEvent).count() == 0

    result = OutreachDeliveryAttemptService(db_session).prepare_initial(
        _request(created.intent, "attempt-one"),
    )
    assert result.attempt.attempt_number == 1
    assert result.event.sequence_number == 1
    assert db_session.query(OutreachDeliveryAttempt).count() == 1
    assert db_session.query(OutreachDeliveryEvent).count() == 1


def test_prepared_event_identity_fingerprint_and_repository_reuse_are_deterministic(db_session):
    _, _, created = _intent(db_session, "event")
    attempt = OutreachDeliveryAttempt(
        outreach_intent_id=created.intent.id, attempt_number=1,
        source_namespace="source", source_event_key="event", request_fingerprint="a" * 64,
    )
    db_session.add(attempt)
    db_session.flush()
    namespace, key = prepared_event_source_identity(attempt.id)
    payload = {"eligibility": "ELIGIBLE", "evaluated_as_of": NOW.isoformat()}
    event_fingerprint = prepared_event_fingerprint(
        delivery_attempt_id=attempt.id, occurred_at=NOW, safe_payload=payload,
    )
    assert event_fingerprint == prepared_event_fingerprint(
        delivery_attempt_id=attempt.id, occurred_at=NOW, safe_payload=dict(reversed(tuple(payload.items()))),
    )
    assert event_fingerprint != prepared_event_fingerprint(
        delivery_attempt_id=attempt.id, occurred_at=NOW + timedelta(seconds=1), safe_payload=payload,
    )
    assert event_fingerprint != prepared_event_fingerprint(
        delivery_attempt_id=attempt.id, occurred_at=NOW, safe_payload={**payload, "eligibility": "OTHER"},
    )
    repository = OutreachDeliveryEventRepository(db_session)
    event = OutreachDeliveryEvent(
        delivery_attempt_id=attempt.id, sequence_number=1, event_type=DeliveryEventType.PREPARED.value,
        occurred_at=NOW, source_namespace=namespace, source_event_key=key,
        event_fingerprint=event_fingerprint, safe_payload=payload,
    )
    assert repository.append_or_reuse(event).reused is False
    duplicate = OutreachDeliveryEvent(
        delivery_attempt_id=attempt.id, sequence_number=1, event_type=DeliveryEventType.PREPARED.value,
        occurred_at=NOW, source_namespace=namespace, source_event_key=key,
        event_fingerprint=event_fingerprint, safe_payload=payload,
    )
    assert repository.append_or_reuse(duplicate).record.id == event.id
    assert "recorded_at" not in inspect.signature(prepared_event_fingerprint).parameters


def test_event_schema_is_append_only_safe_evidence_without_raw_or_provider_fields():
    columns = set(OutreachDeliveryEvent.__table__.columns.keys())
    assert columns == {
        "id", "delivery_attempt_id", "sequence_number", "event_type", "occurred_at",
        "recorded_at", "source_namespace", "source_event_key", "event_fingerprint", "safe_payload",
    }
    assert not {
        "subject", "body", "normalized_value", "destination", "recipient_email",
        "provider", "provider_id", "provider_message_id", "provider_secret",
    }.intersection(columns)
    assert not hasattr(OutreachDeliveryEventRepository, "update")
    assert not hasattr(OutreachDeliveryEventRepository, "delete")


def test_only_initial_preparation_and_no_retry_or_arbitrary_event_service_api_exists():
    public = {
        name for name, value in inspect.getmembers(OutreachDeliveryAttemptService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"prepare_initial"}
    assert not {"retry", "cancel", "append_event", "record_event", "callback", "reconcile"}.intersection(public)


def test_provider_mission_execution_and_workflow_boundaries_are_absent():
    modules = (
        __import__("app.outreach.delivery_contracts", fromlist=["x"]),
        __import__("app.repositories.outreach_delivery_attempt_repository", fromlist=["x"]),
        __import__("app.repositories.outreach_delivery_event_repository", fromlist=["x"]),
        __import__("app.services.outreach_delivery_attempt_service", fromlist=["x"]),
    )
    source = "\n".join(inspect.getsource(module) for module in modules).lower()
    for forbidden in (
        "sessionlocal", ".commit(", "requests.", "httpx.", "provider registry",
        "provider adapter", "missionrecord(", "execution(", "create_mission", "create_execution",
    ):
        assert forbidden not in source
