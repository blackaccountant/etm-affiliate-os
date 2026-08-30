"""Typed immutable contracts for the M9A outreach foundation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.crm.contracts import ContactChannel


OUTREACH_ELIGIBILITY_POLICY_VERSION = "outreach-eligibility-v1"
_MAX_METADATA_BYTES = 4096
_PROHIBITED_METADATA_KEYS = frozenset({
    "destination", "normalized_recipient", "recipient_email", "recipient_phone", "recipient_username",
})


class OutreachError(ValueError):
    """Bounded, non-PII M9 rejection."""

    def __init__(self, category: str, message: str, reason_codes: tuple[str, ...] = ()):
        super().__init__(message)
        self.category = category
        self.reason_codes = reason_codes


class OutreachEligibilityState(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"


class OutreachEligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    CONTACTABILITY_UNAVAILABLE = "CONTACTABILITY_UNAVAILABLE"
    CONTACTABILITY_UNKNOWN = "CONTACTABILITY_UNKNOWN"
    CONTACT_NOT_CONTACTABLE = "CONTACT_NOT_CONTACTABLE"
    LEAD_MISMATCH = "LEAD_MISMATCH"
    CONTACT_POINT_MISMATCH = "CONTACT_POINT_MISMATCH"
    CHANNEL_MISMATCH = "CHANNEL_MISMATCH"
    PURPOSE_MISMATCH = "PURPOSE_MISMATCH"
    MESSAGE_CONTRACT_INVALID = "MESSAGE_CONTRACT_INVALID"


class OutreachContentFormat(str, Enum):
    TEXT = "TEXT"
    HTML = "HTML"


def required_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutreachError("INVALID_CONTRACT", f"{field} is required")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise OutreachError("INVALID_CONTRACT", f"{field} is too long")
    return normalized


def aware_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OutreachError("INVALID_CONTRACT", f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        raise OutreachError("INVALID_CONTRACT", "channel_metadata is too deeply nested")
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 512:
            raise OutreachError("INVALID_CONTRACT", "channel_metadata text is too long")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 32:
            raise OutreachError("INVALID_CONTRACT", "channel_metadata list is too large")
        return [_json_safe(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 32 or not all(isinstance(key, str) and 0 < len(key) <= 64 for key in value):
            raise OutreachError("INVALID_CONTRACT", "channel_metadata keys are invalid")
        if _PROHIBITED_METADATA_KEYS.intersection(key.lower() for key in value):
            raise OutreachError("PII_BOUNDARY_VIOLATION", "recipient routing data is not allowed")
        return {key: _json_safe(item, depth=depth + 1) for key, item in sorted(value.items())}
    raise OutreachError("INVALID_CONTRACT", "channel_metadata must contain JSON-safe primitives")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def fingerprint(value: object, field: str) -> str:
    value = required_text(value, field, 64)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise OutreachError("INVALID_CONTRACT", f"{field} must be a lowercase SHA-256 fingerprint")
    return value


@dataclass(frozen=True)
class PreparedOutreachMessage:
    body: str
    subject: str | None = None
    content_format: str = OutreachContentFormat.TEXT.value
    channel_metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.body, str):
            raise OutreachError("INVALID_CONTRACT", "body must be text")
        body = self.body.replace("\r\n", "\n").replace("\r", "\n")
        if not body.strip():
            raise OutreachError("INVALID_CONTRACT", "body is required")
        if len(body) > 100_000:
            raise OutreachError("INVALID_CONTRACT", "body is too long")
        object.__setattr__(self, "body", body)
        if self.subject is not None:
            object.__setattr__(self, "subject", required_text(self.subject, "subject", 998))
        try:
            object.__setattr__(self, "content_format", OutreachContentFormat(self.content_format).value)
        except (TypeError, ValueError) as exc:
            raise OutreachError("INVALID_CONTRACT", "unsupported content_format") from exc
        metadata = {} if self.channel_metadata is None else _json_safe(self.channel_metadata)
        if len(canonical_json(metadata).encode("utf-8")) > _MAX_METADATA_BYTES:
            raise OutreachError("INVALID_CONTRACT", "channel_metadata is too large")
        object.__setattr__(self, "channel_metadata", metadata)

    @property
    def content_fingerprint(self) -> str:
        return sha256_fingerprint({
            "body": self.body,
            "channel_metadata": self.channel_metadata,
            "content_format": self.content_format,
            "subject": self.subject,
        })


@dataclass(frozen=True)
class CreateOutreachIntentRequest:
    lead_id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    source_namespace: str
    source_event_key: str
    message: PreparedOutreachMessage
    evaluated_as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "lead_id", required_text(self.lead_id, "lead_id", 36))
        object.__setattr__(self, "contact_point_id", required_text(self.contact_point_id, "contact_point_id", 36))
        try:
            object.__setattr__(self, "channel", ContactChannel(self.channel).value)
        except (TypeError, ValueError) as exc:
            raise OutreachError("INVALID_CONTRACT", "unsupported channel") from exc
        object.__setattr__(self, "purpose_key", required_text(self.purpose_key, "purpose_key", 128))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))
        if not isinstance(self.message, PreparedOutreachMessage):
            raise OutreachError("INVALID_CONTRACT", "message must use the prepared M9A contract")
        object.__setattr__(self, "evaluated_as_of", aware_utc(self.evaluated_as_of, "evaluated_as_of"))

    @property
    def request_fingerprint(self) -> str:
        return sha256_fingerprint({
            "channel": self.channel,
            "contact_point_id": self.contact_point_id,
            "content_fingerprint": self.message.content_fingerprint,
            "lead_id": self.lead_id,
            "purpose_key": self.purpose_key,
        })


@dataclass(frozen=True)
class OutreachEligibilityFacts:
    lead_id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    contactability_result: object | None
    message_contract_valid: bool


@dataclass(frozen=True)
class OutreachEligibilityResult:
    state: str
    reason_codes: tuple[str, ...]
    policy_version: str
    decision_fingerprint: str
    evaluated_as_of: datetime | None
    contactability_state: str | None

    @property
    def eligible(self) -> bool:
        return self.state == OutreachEligibilityState.ELIGIBLE.value


@dataclass(frozen=True)
class ContactabilityEvidenceSnapshot:
    lead_id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    state: str
    evaluated_as_of: datetime
    winning_state_event_id: str
    winning_permission_event_id: str
    winning_suppression_event_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    policy_version: str
    decision_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lead_id", required_text(self.lead_id, "lead_id", 36))
        object.__setattr__(self, "contact_point_id", required_text(self.contact_point_id, "contact_point_id", 36))
        try:
            object.__setattr__(self, "channel", ContactChannel(self.channel).value)
        except (TypeError, ValueError) as exc:
            raise OutreachError("INVALID_CONTRACT", "unsupported evidence channel") from exc
        object.__setattr__(self, "purpose_key", required_text(self.purpose_key, "purpose_key", 128))
        if self.state != "CONTACTABLE":
            raise OutreachError("INVALID_EVIDENCE", "persisted creation evidence must be CONTACTABLE")
        object.__setattr__(self, "evaluated_as_of", aware_utc(self.evaluated_as_of, "evaluated_as_of"))
        object.__setattr__(self, "winning_state_event_id", required_text(self.winning_state_event_id, "winning_state_event_id", 36))
        object.__setattr__(self, "winning_permission_event_id", required_text(self.winning_permission_event_id, "winning_permission_event_id", 36))
        suppression_ids = tuple(sorted(set(self.winning_suppression_event_ids)))
        if len(suppression_ids) > 3:
            raise OutreachError("INVALID_EVIDENCE", "too many suppression evidence IDs")
        object.__setattr__(self, "winning_suppression_event_ids", tuple(
            required_text(item, "winning_suppression_event_id", 36) for item in suppression_ids
        ))
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or len(reasons) > 16:
            raise OutreachError("INVALID_EVIDENCE", "contactability reason codes are invalid")
        object.__setattr__(self, "reason_codes", tuple(required_text(item, "reason_code", 64) for item in reasons))
        if self.policy_version != OUTREACH_ELIGIBILITY_POLICY_VERSION:
            raise OutreachError("INVALID_EVIDENCE", "unsupported eligibility policy version")
        object.__setattr__(self, "decision_fingerprint", fingerprint(self.decision_fingerprint, "decision_fingerprint"))

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "contact_point_id": self.contact_point_id,
            "decision_fingerprint": self.decision_fingerprint,
            "evaluated_as_of": self.evaluated_as_of.isoformat(),
            "lead_id": self.lead_id,
            "policy_version": self.policy_version,
            "purpose_key": self.purpose_key,
            "reason_codes": list(self.reason_codes),
            "state": self.state,
            "winning_permission_event_id": self.winning_permission_event_id,
            "winning_state_event_id": self.winning_state_event_id,
            "winning_suppression_event_ids": list(self.winning_suppression_event_ids),
        }


@dataclass(frozen=True)
class OutreachCreationResult:
    intent: object
    message: object
    reused: bool
