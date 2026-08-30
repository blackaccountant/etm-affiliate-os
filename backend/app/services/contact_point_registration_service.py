"""M8B normalization facade over the frozen M8A contact persistence service."""

from __future__ import annotations

from dataclasses import dataclass

from app.crm.contact_normalization import normalize_contact_point
from app.crm.contact_normalization_contracts import ContactNormalizationCandidate, NormalizedContactPoint
from app.crm.contracts import CRMError, ContactPointProvenanceInput, ContactPointStateEventInput
from app.services.contact_point_service import ContactPointService


@dataclass(frozen=True)
class ContactPointRegistrationResult:
    contact_point_id: str
    reused: bool
    normalized: NormalizedContactPoint
    provenance_id: str
    provenance_reused: bool
    state_event_id: str | None = None
    state_event_reused: bool | None = None


class ContactPointRegistrationService:
    def __init__(self, db):
        self.db = db
        self.contacts = ContactPointService(db)

    def register(
        self,
        lead_id: str,
        candidate: ContactNormalizationCandidate,
        provenance: ContactPointProvenanceInput,
        initial_state: ContactPointStateEventInput | None = None,
    ) -> ContactPointRegistrationResult:
        if not isinstance(provenance, ContactPointProvenanceInput):
            raise CRMError("INVALID_CONTRACT", "provenance input must be typed")
        if initial_state is not None and not isinstance(initial_state, ContactPointStateEventInput):
            raise CRMError("INVALID_CONTRACT", "initial state input must be typed")
        normalized = normalize_contact_point(candidate)
        contact = self.contacts.create_or_reuse(
            lead_id,
            kind=normalized.kind,
            normalized_value=normalized.normalized_value,
        )
        provenance_result = self.contacts.attach_provenance(contact.record.id, provenance)
        state_result = None
        if initial_state is not None:
            state_result = self.contacts.append_state_event(contact.record.id, initial_state)
        return ContactPointRegistrationResult(
            contact_point_id=contact.record.id,
            reused=contact.reused,
            normalized=normalized,
            provenance_id=provenance_result.record.id,
            provenance_reused=provenance_result.reused,
            state_event_id=state_result.record.id if state_result else None,
            state_event_reused=state_result.reused if state_result else None,
        )
