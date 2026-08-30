"""Immutable M8D snapshots and deterministic contactability results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.crm.contracts import (
    CRMError,
    ContactChannel,
    ContactPointKind,
    aware_utc,
    enum_value,
    required_text,
)


class ContactabilityState(str, Enum):
    CONTACTABLE = "CONTACTABLE"
    NOT_CONTACTABLE = "NOT_CONTACTABLE"
    UNKNOWN = "UNKNOWN"


class ContactabilityReason(str, Enum):
    ANONYMOUS_SUBJECT = "ANONYMOUS_SUBJECT"
    SUBJECT_UNAVAILABLE = "SUBJECT_UNAVAILABLE"
    NO_COMPATIBLE_CONTACT_POINT = "NO_COMPATIBLE_CONTACT_POINT"
    CHANNEL_INCOMPATIBLE = "CHANNEL_INCOMPATIBLE"
    INFORMATIONAL_CONTACT_KIND = "INFORMATIONAL_CONTACT_KIND"
    CONTACT_POINT_STATE_UNKNOWN = "CONTACT_POINT_STATE_UNKNOWN"
    CONTACT_POINT_INVALID = "CONTACT_POINT_INVALID"
    CONTACT_POINT_RETIRED = "CONTACT_POINT_RETIRED"
    CONTACT_POINT_UNVERIFIED = "CONTACT_POINT_UNVERIFIED"
    PERMISSION_UNKNOWN = "PERMISSION_UNKNOWN"
    PERMISSION_OPTED_OUT = "PERMISSION_OPTED_OUT"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    SUPPRESSED_GLOBAL = "SUPPRESSED_GLOBAL"
    SUPPRESSED_CHANNEL = "SUPPRESSED_CHANNEL"
    SUPPRESSED_CONTACT_POINT = "SUPPRESSED_CONTACT_POINT"
    CONTACTABLE_WITH_CONSENT = "CONTACTABLE_WITH_CONSENT"


@dataclass(frozen=True)
class ContactabilityContext:
    channel: str
    purpose_key: str
    evaluated_as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", enum_value(self.channel, ContactChannel, "channel"))
        object.__setattr__(self, "purpose_key", required_text(self.purpose_key, "purpose_key", 128))
        object.__setattr__(self, "evaluated_as_of", aware_utc(self.evaluated_as_of, "evaluated_as_of"))


@dataclass(frozen=True)
class ContactPointSnapshot:
    id: str
    lead_id: str
    kind: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", required_text(self.id, "contact_point_id", 36))
        object.__setattr__(self, "lead_id", required_text(self.lead_id, "lead_id", 36))
        object.__setattr__(self, "kind", enum_value(self.kind, ContactPointKind, "kind"))


@dataclass(frozen=True)
class ContactPointStateEventSnapshot:
    id: str
    contact_point_id: str
    state: str
    verification_state: str
    occurred_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class PermissionEventSnapshot:
    id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    event_type: str
    jurisdiction_context: str | None
    occurred_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class SuppressionEventSnapshot:
    id: str
    lead_id: str
    contact_point_id: str | None
    scope: str
    channel: str | None
    action: str
    reason: str
    effective_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class ContactabilitySnapshot:
    lead_id: str
    subject_type: str | None
    contact_points: tuple[ContactPointSnapshot, ...]
    state_events: tuple[ContactPointStateEventSnapshot, ...]
    permission_events: tuple[PermissionEventSnapshot, ...]
    suppression_events: tuple[SuppressionEventSnapshot, ...]


@dataclass(frozen=True)
class ResolvedContactPointState:
    effective_state: str | None
    effective_verification: str | None
    winning_event_id: str | None


@dataclass(frozen=True)
class ResolvedPermission:
    effective_permission: str
    winning_event_id: str | None
    jurisdiction_context: str | None


@dataclass(frozen=True)
class SuppressionScopeResolution:
    scope: str
    is_applied: bool
    winning_event_id: str | None
    reason: str | None


@dataclass(frozen=True)
class ResolvedSuppression:
    is_suppressed: bool
    scopes: tuple[SuppressionScopeResolution, ...]
    active_reason_codes: tuple[str, ...]
    winning_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class PointContactabilityResult:
    state: str
    lead_id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    evaluated_as_of: datetime
    effective_contact_state: str | None
    effective_verification: str | None
    effective_permission: str
    suppression: ResolvedSuppression
    reason_codes: tuple[str, ...]
    winning_state_event_id: str | None
    winning_permission_event_id: str | None
    jurisdiction_context: str | None
    channel_compatible: bool


@dataclass(frozen=True)
class LeadContactabilityResult:
    state: str
    lead_id: str
    channel: str
    purpose_key: str
    evaluated_as_of: datetime
    reason_codes: tuple[str, ...]
    point_results: tuple[PointContactabilityResult, ...]
    contactable_point_ids: tuple[str, ...]
    unknown_point_ids: tuple[str, ...]


def require_snapshot(value, expected_type, field: str):
    if not isinstance(value, expected_type):
        raise CRMError("INVALID_CONTRACT", f"{field} must use the immutable M8D contract")
    return value
