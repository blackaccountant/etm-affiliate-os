"""M8A append-only suppression persistence and ownership validation."""

from app.crm.contracts import CRMError, SuppressionEventInput, required_text
from app.models.crm import SuppressionEvent
from app.repositories.contact_point_repository import ContactPointRepository
from app.repositories.lead_repository import LeadRepository
from app.repositories.suppression_repository import SuppressionRepository


class SuppressionService:
    def __init__(self, db):
        self.db = db
        self.leads = LeadRepository(db)
        self.contacts = ContactPointRepository(db)
        self.suppressions = SuppressionRepository(db)

    def append(self, lead_id: str, value: SuppressionEventInput):
        lead = self.leads.get(required_text(lead_id, "lead_id", 36))
        if lead is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")
        if not isinstance(value, SuppressionEventInput):
            raise CRMError("INVALID_CONTRACT", "suppression input must be typed")
        if value.contact_point_id is not None:
            contact_point = self.contacts.get(value.contact_point_id)
            if contact_point is None:
                raise CRMError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
            if contact_point.lead_id != lead.id:
                raise CRMError("SUPPRESSION_OWNERSHIP_CONFLICT", "contact point does not belong to Lead")
        # Serialize every already-created cold authority this suppression can invalidate.
        from app.crm.cold_fact_lock import lock_affected_cold_operations
        lock_affected_cold_operations(self.db, lead.id, value.contact_point_id, None)
        event = SuppressionEvent(
            lead_id=lead.id,
            contact_point_id=value.contact_point_id,
            scope=value.scope,
            channel=value.channel,
            action=value.action,
            reason=value.reason,
            effective_at=value.effective_at,
            source_namespace=value.source_namespace,
            source_event_key=value.source_event_key,
            evidence_fingerprint=value.evidence_fingerprint,
            event_fingerprint=value.fingerprint_for(lead.id),
        )
        return self.suppressions.append(event)
