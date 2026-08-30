"""Focused persistence, idempotency, immutability, and transaction proofs for M9A."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.crm.contracts import ContactPointStateEventInput, PermissionEventInput
from app.models.audience import AudienceSubject
from app.models.crm import ContactPoint, Lead
from app.models.outreach import OutreachIntent, OutreachMessage
from app.outreach.contracts import CreateOutreachIntentRequest, OutreachError, PreparedOutreachMessage
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.outreach_intent_service import OutreachIntentService
from app.services.permission_service import PermissionService


NOW = datetime(2030, 8, 30, 12, tzinfo=timezone.utc)


def _graph(db, suffix):
    subject = AudienceFoundationService(db).create_subject("PERSON")
    lead = LeadService(db).create_or_reuse(subject.id).record
    contact_service = ContactPointService(db)
    contact = contact_service.create_or_reuse(
        lead.id, kind="EMAIL", normalized_value=f"{suffix}@example.com",
    ).record
    contact_service.append_state_event(
        contact.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW, "m9a", f"state-{suffix}"),
    )
    PermissionService(db).append(
        contact.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", NOW, "m9a", f"permission-{suffix}"),
    )
    return subject, lead, contact


def _request(lead, contact, source, *, body="Immutable body", channel="EMAIL", purpose="marketing", at=NOW):
    return CreateOutreachIntentRequest(
        lead.id, contact.id, channel, purpose, "m9a-persistence", source,
        PreparedOutreachMessage(body, "Subject", "TEXT", {"locale": "en"}), at,
    )


def test_new_request_creates_exact_immutable_intent_and_one_to_one_message(db_session):
    _, lead, contact = _graph(db_session, "create")
    request = _request(lead, contact, "create")
    result = OutreachIntentService(db_session).create_or_reuse(request)
    assert result.reused is False
    assert db_session.query(OutreachIntent).count() == db_session.query(OutreachMessage).count() == 1
    assert result.message.outreach_intent_id == result.intent.id
    assert result.intent.request_fingerprint == request.request_fingerprint
    assert result.message.content_fingerprint == request.message.content_fingerprint
    assert result.intent.creation_contactability_state == "CONTACTABLE"
    assert result.intent.contactability_evidence["lead_id"] == lead.id
    assert result.intent.contactability_evidence["contact_point_id"] == contact.id


def test_same_source_and_request_reuses_before_later_contactability_recheck(db_session):
    _, lead, contact = _graph(db_session, "reuse")
    service = OutreachIntentService(db_session)
    request = _request(lead, contact, "reuse")
    first = service.create_or_reuse(request)
    PermissionService(db_session).append(
        contact.id,
        PermissionEventInput("EMAIL", "marketing", "OPTED_OUT", NOW + timedelta(minutes=1), "m9a", "reuse-optout"),
    )
    again = service.create_or_reuse(_request(lead, contact, "reuse", at=NOW + timedelta(minutes=1)))
    assert again.reused is True
    assert (again.intent.id, again.message.id) == (first.intent.id, first.message.id)
    assert service.revalidate_for_execution(first.intent.id, NOW + timedelta(minutes=1)).state == "INELIGIBLE"


@pytest.mark.parametrize("conflict", ["lead", "contact", "channel", "purpose", "content"])
def test_same_source_conflicting_business_request_is_idempotency_conflict(db_session, conflict):
    _, lead, contact = _graph(db_session, f"conflict-{conflict}-one")
    _, other_lead, other_contact = _graph(db_session, f"conflict-{conflict}-two")
    service = OutreachIntentService(db_session)
    service.create_or_reuse(_request(lead, contact, "shared"))
    candidate = {
        "lead": _request(other_lead, other_contact, "shared"),
        "contact": CreateOutreachIntentRequest(
            lead.id, other_contact.id, "EMAIL", "marketing", "m9a-persistence", "shared",
            PreparedOutreachMessage("Immutable body", "Subject", "TEXT", {"locale": "en"}), NOW,
        ),
        "channel": _request(lead, contact, "shared", channel="SMS"),
        "purpose": _request(lead, contact, "shared", purpose="other"),
        "content": _request(lead, contact, "shared", body="Different body"),
    }[conflict]
    with pytest.raises(OutreachError) as error:
        service.create_or_reuse(candidate)
    assert error.value.category == "IDEMPOTENCY_CONFLICT"
    assert db_session.query(OutreachIntent).count() == 1


def test_different_intents_may_use_identical_content_without_global_dedupe(db_session):
    _, lead, contact = _graph(db_session, "duplicate-content")
    service = OutreachIntentService(db_session)
    first = service.create_or_reuse(_request(lead, contact, "first"))
    second = service.create_or_reuse(_request(lead, contact, "second"))
    assert first.intent.id != second.intent.id
    assert first.message.id != second.message.id
    assert first.message.content_fingerprint == second.message.content_fingerprint


def test_fingerprints_are_deterministic_and_authorization_time_is_not_business_identity(db_session):
    _, lead, contact = _graph(db_session, "fingerprints")
    first = _request(lead, contact, "fingerprints", at=NOW)
    later = _request(lead, contact, "fingerprints", at=NOW + timedelta(days=1))
    reordered = CreateOutreachIntentRequest(
        lead.id, contact.id, "EMAIL", "marketing", "m9a-persistence", "fingerprints",
        PreparedOutreachMessage("Immutable body", "Subject", "TEXT", {"locale": "en"}), NOW,
    )
    assert first.request_fingerprint == later.request_fingerprint == reordered.request_fingerprint
    assert first.message.content_fingerprint == reordered.message.content_fingerprint


def test_models_exclude_recipient_provider_qualification_lifecycle_and_mutable_contactability_fields():
    intent_columns = set(OutreachIntent.__table__.columns.keys())
    message_columns = set(OutreachMessage.__table__.columns.keys())
    prohibited = {
        "recipient_email", "recipient_phone", "recipient_username", "normalized_recipient", "destination",
        "provider", "provider_key", "provider_secret", "qualification", "lifecycle", "contactable",
        "current_contactability_state",
    }
    assert not intent_columns.intersection(prohibited)
    assert not message_columns.intersection(prohibited)
    assert "outreach_intent_id" in message_columns and "content_fingerprint" in message_columns


def test_contact_point_lead_ownership_mismatch_is_bounded_and_creates_nothing(db_session):
    _, lead, _ = _graph(db_session, "owner-one")
    _, _, other_contact = _graph(db_session, "owner-two")
    request = CreateOutreachIntentRequest(
        lead.id, other_contact.id, "EMAIL", "marketing", "m9a-persistence", "ownership",
        PreparedOutreachMessage("Body"), NOW,
    )
    with pytest.raises(OutreachError) as error:
        OutreachIntentService(db_session).create_or_reuse(request)
    assert error.value.category == "CONTACT_POINT_LEAD_MISMATCH"
    assert db_session.query(OutreachIntent).count() == db_session.query(OutreachMessage).count() == 0


def test_unknown_contactability_creates_no_intent_or_message(db_session):
    subject = AudienceFoundationService(db_session).create_subject("PERSON")
    lead = LeadService(db_session).create_or_reuse(subject.id).record
    contact = ContactPointService(db_session).create_or_reuse(
        lead.id, kind="EMAIL", normalized_value="unknown@example.com",
    ).record
    with pytest.raises(OutreachError) as error:
        OutreachIntentService(db_session).create_or_reuse(_request(lead, contact, "unknown"))
    assert error.value.category == "INELIGIBLE"
    assert db_session.query(OutreachIntent).count() == db_session.query(OutreachMessage).count() == 0


def test_intent_and_message_are_caller_owned_and_rollback_atomically(db_session, db_session_factory):
    subject, lead, contact = _graph(db_session, "rollback")
    ids = subject.id, lead.id, contact.id
    db_session.commit()
    db_session.execute(text("BEGIN"))
    result = OutreachIntentService(db_session).create_or_reuse(_request(lead, contact, "rollback"))
    intent_id, message_id = result.intent.id, result.message.id
    assert db_session.in_transaction()
    assert db_session.get(OutreachIntent, intent_id) and db_session.get(OutreachMessage, message_id)
    db_session.rollback()
    verifier = db_session_factory()
    try:
        assert verifier.get(OutreachIntent, intent_id) is None
        assert verifier.get(OutreachMessage, message_id) is None
        assert verifier.get(AudienceSubject, ids[0]) is not None
        assert verifier.get(Lead, ids[1]) is not None
        assert verifier.get(ContactPoint, ids[2]) is not None
    finally:
        verifier.close()


def test_channel_metadata_rejects_routing_pii():
    for key in ("recipient_email", "recipient_phone", "recipient_username", "destination"):
        with pytest.raises(OutreachError) as error:
            PreparedOutreachMessage("Body", channel_metadata={key: "secret"})
        assert error.value.category == "PII_BOUNDARY_VIOLATION"
