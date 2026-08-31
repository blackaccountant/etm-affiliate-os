"""Cold-owned ephemeral EMAIL boundary for the B3 planning stage.

This module deliberately has no provider imports or transport behavior.  The
recipient value is retained only long enough to derive the planning fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.crm import ContactPoint
from app.outreach.contracts import OutreachError, required_text, sha256_fingerprint


@dataclass(frozen=True, repr=False)
class ColdEphemeralRecipient:
    """Validated EMAIL routing data that cannot be serialized or displayed."""

    channel: str
    _email: str

    def __post_init__(self) -> None:
        if self.channel != "EMAIL":
            raise OutreachError("UNSUPPORTED_CHANNEL", "cold T3 supports EMAIL only")
        value = required_text(self._email, "recipient", 320)
        if value != value.strip() or value.count("@") != 1 or any(char.isspace() for char in value):
            raise OutreachError("INVALID_RECIPIENT", "email routing representation is invalid")
        local, domain = value.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise OutreachError("INVALID_RECIPIENT", "email routing representation is invalid")
        object.__setattr__(self, "_email", f"{local}@{domain.lower()}")

    def __repr__(self) -> str:
        return "ColdEphemeralRecipient(channel='EMAIL', value=<redacted>)"

    __str__ = __repr__

    def fingerprint(self) -> str:
        """Return a domain-separated digest without releasing the routing value."""
        return sha256_fingerprint({
            "schema": "cold-recipient-v1",
            "channel": self.channel,
            "recipient": self._email,
        })


class ColdRecipientResolutionService:
    """Resolve only the contact point the caller already authorized and locked."""

    @staticmethod
    def resolve_email(*, locked_contact_point: ContactPoint, lead_id: str, contact_point_id: str) -> ColdEphemeralRecipient:
        if locked_contact_point is None:
            raise OutreachError("CONTACT_POINT_NOT_FOUND", "contact point does not exist")
        if locked_contact_point.id != contact_point_id or locked_contact_point.lead_id != lead_id:
            raise OutreachError("CONTACT_POINT_LEAD_MISMATCH", "contact point does not belong to Lead")
        if locked_contact_point.kind != "EMAIL":
            raise OutreachError("CHANNEL_MISMATCH", "contact point is not EMAIL-compatible")
        return ColdEphemeralRecipient("EMAIL", locked_contact_point.normalized_value)
