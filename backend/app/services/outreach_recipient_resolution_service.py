"""Resolve a consented EMAIL routing value ephemerally from frozen intent identity."""

from app.models.crm import ContactPoint
from app.outreach.contracts import OutreachError
from app.outreach.provider_contracts import EphemeralRecipient


class OutreachRecipientResolutionService:
    def __init__(self, db):
        self.db = db

    def resolve_email(self, *, lead_id: str, contact_point_id: str, channel: str) -> EphemeralRecipient:
        if channel != "EMAIL":
            raise OutreachError("UNSUPPORTED_CHANNEL", "M9C1 supports consented EMAIL only")
        contact = self.db.get(ContactPoint, contact_point_id)
        if contact is None:
            raise OutreachError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
        if contact.lead_id != lead_id:
            raise OutreachError("CONTACT_POINT_LEAD_MISMATCH", "contact point does not belong to Lead")
        if contact.kind != "EMAIL":
            raise OutreachError("CHANNEL_MISMATCH", "contact point is not EMAIL-compatible")
        return EphemeralRecipient("EMAIL", contact.normalized_value)
