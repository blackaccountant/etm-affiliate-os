"""Typed, immutable contracts for the M8A CRM persistence boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum


class ContactPointKind(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    TELEGRAM = "TELEGRAM"
    WEBSITE = "WEBSITE"
    SOCIAL_PROFILE = "SOCIAL_PROFILE"


class ContactChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"


class ContactPointState(str, Enum):
    ACTIVE = "ACTIVE"
    INVALID = "INVALID"
    RETIRED = "RETIRED"


class ContactPointVerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class ContactProvenanceType(str, Enum):
    USER_PROVIDED = "USER_PROVIDED"
    PUBLIC_BUSINESS_SOURCE = "PUBLIC_BUSINESS_SOURCE"
    WEBSITE = "WEBSITE"
    FORM_SUBMISSION = "FORM_SUBMISSION"
    IMPORT = "IMPORT"
    AFFILIATE_SYSTEM = "AFFILIATE_SYSTEM"
    MANUAL = "MANUAL"


class PermissionEventType(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONSENTED = "CONSENTED"
    OPTED_OUT = "OPTED_OUT"
    REVOKED = "REVOKED"


class EffectivePermissionState(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONSENTED = "CONSENTED"
    OPTED_OUT = "OPTED_OUT"
    REVOKED = "REVOKED"


class SuppressionAction(str, Enum):
    APPLIED = "APPLIED"
    LIFTED = "LIFTED"


class SuppressionScope(str, Enum):
    GLOBAL_LEAD = "GLOBAL_LEAD"
    LEAD_CHANNEL = "LEAD_CHANNEL"
    CONTACT_POINT_CHANNEL = "CONTACT_POINT_CHANNEL"


class SuppressionReason(str, Enum):
    OPT_OUT = "OPT_OUT"
    BOUNCE = "BOUNCE"
    COMPLAINT = "COMPLAINT"
    MANUAL = "MANUAL"
    COMPLIANCE = "COMPLIANCE"


class CRMError(ValueError):
    """Safe typed rejection from the CRM persistence boundary."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class PersistenceResult:
    record: object
    reused: bool


def enum_value(value: object, enum_type: type[Enum], field: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CRMError("INVALID_CONTRACT", f"unsupported {field}") from exc


def required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CRMError("INVALID_CONTRACT", f"{field} is required")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise CRMError("INVALID_CONTRACT", f"{field} is too long")
    return normalized


def optional_text(value: object | None, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return required_text(value, field, maximum)


def fingerprint(value: object | None, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    value = required_text(value, field, 64)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise CRMError("INVALID_CONTRACT", f"{field} must be a lowercase SHA-256 fingerprint")
    return value


def aware_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CRMError("INVALID_CONTRACT", f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _event_fingerprint(namespace: str, payload: object) -> str:
    encoded = json.dumps(
        {"namespace": namespace, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ContactPointProvenanceInput:
    source_type: str
    source_namespace: str
    source_event_id: str
    observed_at: datetime | None = None
    captured_at: datetime | None = None
    evidence_reference: str | None = None
    evidence_fingerprint: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "source_type", enum_value(self.source_type, ContactProvenanceType, "source_type"))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_id", required_text(self.source_event_id, "source_event_id", 512))
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", aware_utc(self.observed_at, "observed_at"))
        if self.captured_at is not None:
            object.__setattr__(self, "captured_at", aware_utc(self.captured_at, "captured_at"))
        object.__setattr__(self, "evidence_reference", optional_text(self.evidence_reference, "evidence_reference", 2000))
        object.__setattr__(self, "evidence_fingerprint", fingerprint(self.evidence_fingerprint, "evidence_fingerprint", optional=True))

    def fingerprint_for(self, contact_point_id: str) -> str:
        return _event_fingerprint("crm-contact-provenance-v1", {"contact_point_id": contact_point_id, **asdict(self)})


@dataclass(frozen=True)
class ContactPointStateEventInput:
    state: str
    verification_state: str
    occurred_at: datetime
    source_namespace: str
    source_event_key: str

    def __post_init__(self):
        object.__setattr__(self, "state", enum_value(self.state, ContactPointState, "state"))
        object.__setattr__(self, "verification_state", enum_value(self.verification_state, ContactPointVerificationState, "verification_state"))
        object.__setattr__(self, "occurred_at", aware_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))

    def fingerprint_for(self, contact_point_id: str) -> str:
        return _event_fingerprint("crm-contact-state-event-v1", {"contact_point_id": contact_point_id, **asdict(self)})


@dataclass(frozen=True)
class PermissionEventInput:
    channel: str
    purpose_key: str
    event_type: str
    occurred_at: datetime
    source_namespace: str
    source_event_key: str
    jurisdiction_context: str | None = None
    evidence_fingerprint: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "channel", enum_value(self.channel, ContactChannel, "channel"))
        object.__setattr__(self, "purpose_key", required_text(self.purpose_key, "purpose_key", 128))
        object.__setattr__(self, "event_type", enum_value(self.event_type, PermissionEventType, "event_type"))
        object.__setattr__(self, "occurred_at", aware_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))
        object.__setattr__(self, "jurisdiction_context", optional_text(self.jurisdiction_context, "jurisdiction_context", 128))
        object.__setattr__(self, "evidence_fingerprint", fingerprint(self.evidence_fingerprint, "evidence_fingerprint", optional=True))

    def fingerprint_for(self, contact_point_id: str) -> str:
        return _event_fingerprint("crm-permission-event-v1", {"contact_point_id": contact_point_id, **asdict(self)})


@dataclass(frozen=True)
class SuppressionEventInput:
    scope: str
    action: str
    reason: str
    effective_at: datetime
    source_namespace: str
    source_event_key: str
    contact_point_id: str | None = None
    channel: str | None = None
    evidence_fingerprint: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "scope", enum_value(self.scope, SuppressionScope, "scope"))
        object.__setattr__(self, "action", enum_value(self.action, SuppressionAction, "action"))
        object.__setattr__(self, "reason", enum_value(self.reason, SuppressionReason, "reason"))
        object.__setattr__(self, "effective_at", aware_utc(self.effective_at, "effective_at"))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))
        object.__setattr__(self, "contact_point_id", optional_text(self.contact_point_id, "contact_point_id", 36))
        if self.channel is not None:
            object.__setattr__(self, "channel", enum_value(self.channel, ContactChannel, "channel"))
        object.__setattr__(self, "evidence_fingerprint", fingerprint(self.evidence_fingerprint, "evidence_fingerprint", optional=True))
        valid = (
            self.scope == SuppressionScope.GLOBAL_LEAD.value and self.contact_point_id is None and self.channel is None
        ) or (
            self.scope == SuppressionScope.LEAD_CHANNEL.value and self.contact_point_id is None and self.channel is not None
        ) or (
            self.scope == SuppressionScope.CONTACT_POINT_CHANNEL.value and self.contact_point_id is not None and self.channel is not None
        )
        if not valid:
            raise CRMError("INVALID_SUPPRESSION_SCOPE", "suppression scope fields are inconsistent")

    def fingerprint_for(self, lead_id: str) -> str:
        return _event_fingerprint("crm-suppression-event-v1", {"lead_id": lead_id, **asdict(self)})
