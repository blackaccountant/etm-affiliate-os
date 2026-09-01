"""M8A immutable contact-point, provenance, and state-event persistence."""

from app.crm.contracts import (
    CRMError,
    ContactPointKind,
    ContactPointProvenanceInput,
    ContactPointStateEventInput,
    enum_value,
    required_text,
)
from app.models.audience import AudienceSubject
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent
from app.repositories.contact_point_repository import ContactPointRepository
from app.repositories.lead_repository import LeadRepository


class ContactPointService:
    def __init__(self, db):
        self.db = db
        self.leads = LeadRepository(db)
        self.contacts = ContactPointRepository(db)

    def create_or_reuse(self, lead_id: str, *, kind: str, normalized_value: str):
        lead = self.leads.get(required_text(lead_id, "lead_id", 36))
        if lead is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")
        if lead.subject_id is None:
            raise CRMError("LEAD_SUBJECT_REQUIRED", "subjectless Lead cannot own contact points")
        subject = self.db.get(AudienceSubject, lead.subject_id)
        if subject is None:
            raise CRMError("SUBJECT_NOT_FOUND", "Lead AudienceSubject does not exist")
        if subject.subject_type == "ANONYMOUS":
            raise CRMError("ANONYMOUS_CONTACT_FORBIDDEN", "anonymous Lead cannot own contact points")
        kind = enum_value(kind, ContactPointKind, "kind")
        value = required_text(normalized_value, "normalized_value", 2000)
        if value != normalized_value:
            raise CRMError("INVALID_CONTRACT", "normalized_value must not contain surrounding whitespace")
        return self.contacts.create_or_reuse(ContactPoint(lead_id=lead.id, kind=kind, normalized_value=value))

    def attach_provenance(self, contact_point_id: str, value: ContactPointProvenanceInput):
        contact_point = self._contact(contact_point_id)
        from app.crm.cold_fact_lock import lock_affected_cold_operations
        lock_affected_cold_operations(self.db, contact_point.lead_id, contact_point.id)
        if not isinstance(value, ContactPointProvenanceInput):
            raise CRMError("INVALID_CONTRACT", "provenance input must be typed")
        record = ContactPointProvenance(
            contact_point_id=contact_point.id,
            source_type=value.source_type,
            source_namespace=value.source_namespace,
            source_event_id=value.source_event_id,
            observed_at=value.observed_at,
            captured_at=value.captured_at,
            evidence_reference=value.evidence_reference,
            evidence_fingerprint=value.evidence_fingerprint,
            provenance_fingerprint=value.fingerprint_for(contact_point.id),
        )
        return self.contacts.append_provenance(record)

    def append_state_event(self, contact_point_id: str, value: ContactPointStateEventInput):
        contact_point = self._contact(contact_point_id)
        from app.crm.cold_fact_lock import lock_affected_cold_operations
        lock_affected_cold_operations(self.db, contact_point.lead_id, contact_point.id)
        if not isinstance(value, ContactPointStateEventInput):
            raise CRMError("INVALID_CONTRACT", "state-event input must be typed")
        record = ContactPointStateEvent(
            contact_point_id=contact_point.id,
            state=value.state,
            verification_state=value.verification_state,
            occurred_at=value.occurred_at,
            source_namespace=value.source_namespace,
            source_event_key=value.source_event_key,
            event_fingerprint=value.fingerprint_for(contact_point.id),
        )
        return self.contacts.append_state_event(record)

    def _contact(self, contact_point_id: str) -> ContactPoint:
        record = self.contacts.get(required_text(contact_point_id, "contact_point_id", 36))
        if record is None:
            raise CRMError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
        return record
