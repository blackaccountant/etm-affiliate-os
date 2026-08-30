"""Focused local proofs for the M8A CRM persistence foundation."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.crm.contracts import (
    CRMError,
    ContactPointProvenanceInput,
    ContactPointStateEventInput,
    PermissionEventInput,
    PermissionEventType,
    SuppressionEventInput,
)
from app.models.audience import AudienceSubject
from app.models.crm import (
    ContactPoint,
    ContactPointProvenance,
    ContactPointStateEvent,
    Lead,
    PermissionEvent,
    SuppressionEvent,
)
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def _subject(db, subject_type="PERSON"):
    return AudienceFoundationService(db).create_subject(subject_type)


def _lead(db, subject_type="PERSON"):
    subject = _subject(db, subject_type)
    return subject, LeadService(db).create_or_reuse(subject.id).record


def _contact(db, *, subject_type="PERSON", kind="EMAIL", value="person@example.com"):
    subject, lead = _lead(db, subject_type)
    contact = ContactPointService(db).create_or_reuse(lead.id, kind=kind, normalized_value=value).record
    return subject, lead, contact


def _permission(key, event_type="CONSENTED", *, channel="EMAIL", purpose="affiliate-marketing"):
    return PermissionEventInput(channel, purpose, event_type, NOW, "m8a-test", key)


def _suppression(key, *, scope="GLOBAL_LEAD", action="APPLIED", reason="MANUAL", contact=None, channel=None):
    return SuppressionEventInput(scope, action, reason, NOW, "m8a-test", key, contact, channel)


def test_person_organization_and_one_lead_per_subject_reuse(db_session):
    service = LeadService(db_session)
    person = _subject(db_session, "PERSON")
    organization = _subject(db_session, "ORGANIZATION")
    person_first = service.create_or_reuse(person.id)
    person_again = service.create_or_reuse(person.id)
    organization_result = service.create_or_reuse(organization.id)
    assert person_first.reused is False
    assert person_again.reused is True
    assert person_again.record.id == person_first.record.id
    assert organization_result.record.subject_id == organization.id
    assert db_session.query(Lead).count() == 2
    assert db_session.in_transaction()


def test_anonymous_shell_allowed_but_contact_attachment_rejected(db_session):
    anonymous = _subject(db_session, "ANONYMOUS")
    lead = LeadService(db_session).create_or_reuse(anonymous.id).record
    assert lead.subject_id == anonymous.id
    with pytest.raises(CRMError) as error:
        ContactPointService(db_session).create_or_reuse(lead.id, kind="EMAIL", normalized_value="hidden@example.com")
    assert error.value.category == "ANONYMOUS_CONTACT_FORBIDDEN"
    assert db_session.query(ContactPoint).count() == 0


def test_contact_point_create_reuse_global_conflict_and_immutable_value(db_session):
    _, first_lead = _lead(db_session)
    _, second_lead = _lead(db_session, "ORGANIZATION")
    service = ContactPointService(db_session)
    first = service.create_or_reuse(first_lead.id, kind="EMAIL", normalized_value="exact@example.com")
    again = service.create_or_reuse(first_lead.id, kind="EMAIL", normalized_value="exact@example.com")
    assert first.reused is False and again.reused is True and first.record.id == again.record.id
    with pytest.raises(CRMError) as error:
        service.create_or_reuse(second_lead.id, kind="EMAIL", normalized_value="exact@example.com")
    assert error.value.category == "CONTACT_POINT_OWNERSHIP_CONFLICT"
    assert "exact@example.com" not in str(error.value)
    corrected = service.create_or_reuse(first_lead.id, kind="EMAIL", normalized_value="corrected@example.com")
    assert corrected.record.id != first.record.id
    assert db_session.get(ContactPoint, first.record.id).normalized_value == "exact@example.com"
    with pytest.raises(CRMError):
        service.create_or_reuse(first_lead.id, kind="EMAIL", normalized_value=" exact@example.com ")


def test_provenance_is_multi_source_immutable_reusable_and_conflict_safe(db_session):
    _, _, contact = _contact(db_session)
    service = ContactPointService(db_session)
    first_input = ContactPointProvenanceInput("USER_PROVIDED", "form", "submission-1", NOW, NOW, evidence_fingerprint="a" * 64)
    second_input = ContactPointProvenanceInput("WEBSITE", "site", "page-1", NOW, NOW, evidence_reference="https://example.com/contact")
    first = service.attach_provenance(contact.id, first_input)
    again = service.attach_provenance(contact.id, first_input)
    second = service.attach_provenance(contact.id, second_input)
    assert first.reused is False and again.reused is True and second.reused is False
    assert db_session.query(ContactPointProvenance).filter_by(contact_point_id=contact.id).count() == 2
    conflict = ContactPointProvenanceInput("MANUAL", "form", "submission-1", NOW, NOW)
    with pytest.raises(CRMError) as error:
        service.attach_provenance(contact.id, conflict)
    assert error.value.category == "IDEMPOTENCY_CONFLICT"


def test_contact_state_events_are_append_only_and_verification_is_independent(db_session):
    _, _, contact = _contact(db_session)
    service = ContactPointService(db_session)
    active = ContactPointStateEventInput("ACTIVE", "UNVERIFIED", NOW, "m8a-test", "state-1")
    verified = ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW + timedelta(seconds=1), "m8a-test", "state-2")
    first = service.append_state_event(contact.id, active)
    again = service.append_state_event(contact.id, active)
    service.append_state_event(contact.id, verified)
    assert first.reused is False and again.reused is True
    events = db_session.query(ContactPointStateEvent).filter_by(contact_point_id=contact.id).order_by(ContactPointStateEvent.occurred_at).all()
    assert [(event.state, event.verification_state) for event in events] == [("ACTIVE", "UNVERIFIED"), ("ACTIVE", "VERIFIED")]


def test_permission_history_scoping_reuse_and_conflicting_key(db_session):
    _, _, contact = _contact(db_session)
    service = PermissionService(db_session)
    consent = _permission("permission-1")
    first = service.append(contact.id, consent)
    again = service.append(contact.id, consent)
    opted_out = service.append(contact.id, _permission("permission-2", "OPTED_OUT"))
    revoked = service.append(contact.id, _permission("permission-3", "REVOKED", purpose="product-updates"))
    assert first.reused is False and again.reused is True
    assert (opted_out.record.event_type, revoked.record.event_type) == ("OPTED_OUT", "REVOKED")
    assert {(row.channel, row.purpose_key) for row in db_session.query(PermissionEvent)} == {
        ("EMAIL", "affiliate-marketing"), ("EMAIL", "product-updates")
    }
    with pytest.raises(CRMError) as error:
        service.append(contact.id, _permission("permission-1", "REVOKED"))
    assert error.value.category == "IDEMPOTENCY_CONFLICT"


def test_permission_channel_compatibility_and_informational_kinds(db_session):
    _, _, phone = _contact(db_session, kind="PHONE", value="+2348000000000")
    service = PermissionService(db_session)
    service.append(phone.id, _permission("sms", channel="SMS"))
    service.append(phone.id, _permission("whatsapp", channel="WHATSAPP"))
    with pytest.raises(CRMError) as error:
        service.append(phone.id, _permission("email-on-phone", channel="EMAIL"))
    assert error.value.category == "CHANNEL_KIND_MISMATCH"
    for index, kind in enumerate(("WEBSITE", "SOCIAL_PROFILE")):
        _, _, informational = _contact(db_session, kind=kind, value=f"{kind.lower()}:{index}")
        with pytest.raises(CRMError) as error:
            service.append(informational.id, _permission(f"informational-{index}"))
        assert error.value.category == "CHANNEL_KIND_MISMATCH"


def test_suppression_scopes_history_reuse_and_conflicting_key(db_session):
    _, lead, contact = _contact(db_session)
    service = SuppressionService(db_session)
    global_event = _suppression("global")
    first = service.append(lead.id, global_event)
    again = service.append(lead.id, global_event)
    service.append(lead.id, _suppression("lead-email", scope="LEAD_CHANNEL", channel="EMAIL"))
    service.append(lead.id, _suppression("point-email", scope="CONTACT_POINT_CHANNEL", contact=contact.id, channel="EMAIL"))
    service.append(lead.id, _suppression("global-lift", action="LIFTED"))
    assert first.reused is False and again.reused is True
    assert db_session.query(SuppressionEvent).filter_by(lead_id=lead.id).count() == 4
    assert {row.action for row in db_session.query(SuppressionEvent)} == {"APPLIED", "LIFTED"}
    with pytest.raises(CRMError) as error:
        service.append(lead.id, _suppression("global", action="LIFTED"))
    assert error.value.category == "IDEMPOTENCY_CONFLICT"


def test_suppression_contract_and_contact_ownership_are_strict(db_session):
    with pytest.raises(CRMError) as error:
        _suppression("bad", scope="GLOBAL_LEAD", channel="EMAIL")
    assert error.value.category == "INVALID_SUPPRESSION_SCOPE"
    _, first_lead, _ = _contact(db_session, value="first@example.com")
    _, second_lead, second_contact = _contact(db_session, value="second@example.com")
    event = _suppression("wrong-owner", scope="CONTACT_POINT_CHANNEL", contact=second_contact.id, channel="EMAIL")
    with pytest.raises(CRMError) as error:
        SuppressionService(db_session).append(first_lead.id, event)
    assert error.value.category == "SUPPRESSION_OWNERSHIP_CONFLICT"
    assert second_lead.id != first_lead.id


def test_contracts_reject_invalid_values_and_prohibited_legal_bases_are_absent():
    with pytest.raises(CRMError):
        PermissionEventInput("EMAIL", " ", "CONSENTED", NOW, "test", "blank-purpose")
    with pytest.raises(CRMError):
        ContactPointProvenanceInput("MANUAL", "test", "event", evidence_fingerprint="not-a-fingerprint")
    with pytest.raises(CRMError):
        PermissionEventInput("EMAIL", "marketing", "LEGITIMATE_INTEREST", NOW, "test", "legal")
    with pytest.raises(CRMError):
        PermissionEventInput("EMAIL", "marketing", "BUSINESS_CONTACT", NOW, "test", "business")
    assert {item.value for item in PermissionEventType} == {"UNKNOWN", "CONSENTED", "OPTED_OUT", "REVOKED"}


def test_lead_has_no_qualification_contactability_or_consent_flags():
    columns = set(Lead.__table__.columns.keys())
    assert columns == {"id", "subject_id", "created_at"}
    assert not columns & {"qualification_score", "qualification_status", "contactable", "consented", "suppressed"}


def test_full_graph_is_caller_owned_and_caller_rollback_is_total(db_session, db_session_factory):
    subject = _subject(db_session, "PERSON")
    subject_id = subject.id
    db_session.commit()
    db_session.execute(text("BEGIN"))
    lead = LeadService(db_session).create_or_reuse(subject_id).record
    contact_service = ContactPointService(db_session)
    contact = contact_service.create_or_reuse(lead.id, kind="EMAIL", normalized_value="rollback@example.com").record
    contact_service.attach_provenance(contact.id, ContactPointProvenanceInput("MANUAL", "rollback", "provenance", NOW, NOW))
    contact_service.append_state_event(contact.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW, "rollback", "state"))
    PermissionService(db_session).append(contact.id, PermissionEventInput("EMAIL", "marketing", "CONSENTED", NOW, "rollback", "permission"))
    SuppressionService(db_session).append(lead.id, SuppressionEventInput("LEAD_CHANNEL", "APPLIED", "MANUAL", NOW, "rollback", "suppression", channel="EMAIL"))
    assert db_session.in_transaction()
    for model in (Lead, ContactPoint, ContactPointProvenance, ContactPointStateEvent, PermissionEvent, SuppressionEvent):
        assert db_session.query(model).count() == 1
    db_session.rollback()
    verifier = db_session_factory()
    try:
        for model in (Lead, ContactPoint, ContactPointProvenance, ContactPointStateEvent, PermissionEvent, SuppressionEvent):
            assert verifier.query(model).count() == 0
        assert verifier.query(AudienceSubject).filter_by(id=subject_id).count() == 1
    finally:
        verifier.close()
