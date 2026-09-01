"""M8A append-only, channel-scoped permission persistence."""

from app.crm.contracts import CRMError, PermissionEventInput, required_text
from app.models.crm import PermissionEvent
from app.repositories.contact_point_repository import ContactPointRepository
from app.repositories.permission_repository import PermissionRepository


_COMPATIBLE_CHANNELS = {
    "EMAIL": {"EMAIL"},
    "PHONE": {"SMS", "WHATSAPP"},
    "TELEGRAM": {"TELEGRAM"},
    "WEBSITE": set(),
    "SOCIAL_PROFILE": set(),
}


class PermissionService:
    def __init__(self, db):
        self.db = db
        self.contacts = ContactPointRepository(db)
        self.permissions = PermissionRepository(db)

    def append(self, contact_point_id: str, value: PermissionEventInput):
        contact_point = self.contacts.get(required_text(contact_point_id, "contact_point_id", 36))
        if contact_point is None:
            raise CRMError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
        if not isinstance(value, PermissionEventInput):
            raise CRMError("INVALID_CONTRACT", "permission input must be typed")
        if value.channel not in _COMPATIBLE_CHANNELS[contact_point.kind]:
            raise CRMError("CHANNEL_KIND_MISMATCH", "channel is incompatible with contact-point kind")
        if value.channel == "EMAIL":
            from app.crm.cold_fact_lock import lock_affected_cold_operations
            lock_affected_cold_operations(self.db, contact_point.lead_id, contact_point.id, value.purpose_key)
        event = PermissionEvent(
            contact_point_id=contact_point.id,
            channel=value.channel,
            purpose_key=value.purpose_key,
            event_type=value.event_type,
            jurisdiction_context=value.jurisdiction_context,
            occurred_at=value.occurred_at,
            source_namespace=value.source_namespace,
            source_event_key=value.source_event_key,
            evidence_fingerprint=value.evidence_fingerprint,
            event_fingerprint=value.fingerprint_for(contact_point.id),
        )
        return self.permissions.append(event)
