"""Typed provider-neutral contracts for M9B delivery preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.crm.contracts import ContactChannel
from app.outreach.contracts import (
    OUTREACH_ELIGIBILITY_POLICY_VERSION,
    OutreachError,
    aware_utc,
    fingerprint,
    required_text,
    sha256_fingerprint,
)


DELIVERY_PREPARATION_EVIDENCE_VERSION = "outreach-delivery-preparation-v1"
PREPARED_EVENT_SOURCE_NAMESPACE = "outreach-delivery-prepared"


class DeliveryEventType(str, Enum):
    PREPARED = "PREPARED"


@dataclass(frozen=True)
class PrepareDeliveryAttemptRequest:
    outreach_intent_id: str
    source_namespace: str
    source_event_key: str
    evaluated_as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "outreach_intent_id", required_text(self.outreach_intent_id, "outreach_intent_id", 36))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))
        object.__setattr__(self, "evaluated_as_of", aware_utc(self.evaluated_as_of, "evaluated_as_of"))

    @property
    def request_fingerprint(self) -> str:
        return sha256_fingerprint({"outreach_intent_id": self.outreach_intent_id})


@dataclass(frozen=True)
class PreparedDeliveryEvidence:
    outreach_intent_id: str
    lead_id: str
    contact_point_id: str
    channel: str
    purpose_key: str
    eligibility: str
    contactability_state: str
    evaluated_as_of: datetime
    policy_version: str
    decision_fingerprint: str
    winning_state_event_id: str
    winning_permission_event_id: str
    winning_suppression_event_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_version: str = DELIVERY_PREPARATION_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        for field in ("outreach_intent_id", "lead_id", "contact_point_id"):
            object.__setattr__(self, field, required_text(getattr(self, field), field, 36))
        try:
            object.__setattr__(self, "channel", ContactChannel(self.channel).value)
        except (TypeError, ValueError) as exc:
            raise OutreachError("INVALID_EVIDENCE", "unsupported preparation channel") from exc
        object.__setattr__(self, "purpose_key", required_text(self.purpose_key, "purpose_key", 128))
        if self.eligibility != "ELIGIBLE" or self.contactability_state != "CONTACTABLE":
            raise OutreachError("INVALID_EVIDENCE", "PREPARED evidence must be eligible and contactable")
        object.__setattr__(self, "evaluated_as_of", aware_utc(self.evaluated_as_of, "evaluated_as_of"))
        if self.policy_version != OUTREACH_ELIGIBILITY_POLICY_VERSION:
            raise OutreachError("INVALID_EVIDENCE", "unsupported eligibility policy version")
        object.__setattr__(self, "decision_fingerprint", fingerprint(self.decision_fingerprint, "decision_fingerprint"))
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
            raise OutreachError("INVALID_EVIDENCE", "preparation reason codes are invalid")
        object.__setattr__(self, "reason_codes", tuple(required_text(item, "reason_code", 64) for item in reasons))
        if self.evidence_version != DELIVERY_PREPARATION_EVIDENCE_VERSION:
            raise OutreachError("INVALID_EVIDENCE", "unsupported preparation evidence version")

    def to_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "contact_point_id": self.contact_point_id,
            "contactability_state": self.contactability_state,
            "decision_fingerprint": self.decision_fingerprint,
            "eligibility": self.eligibility,
            "evaluated_as_of": self.evaluated_as_of.isoformat(),
            "evidence_version": self.evidence_version,
            "lead_id": self.lead_id,
            "outreach_intent_id": self.outreach_intent_id,
            "policy_version": self.policy_version,
            "purpose_key": self.purpose_key,
            "reason_codes": list(self.reason_codes),
            "winning_permission_event_id": self.winning_permission_event_id,
            "winning_state_event_id": self.winning_state_event_id,
            "winning_suppression_event_ids": list(self.winning_suppression_event_ids),
        }


def prepared_event_source_identity(delivery_attempt_id: object) -> tuple[str, str]:
    return PREPARED_EVENT_SOURCE_NAMESPACE, required_text(delivery_attempt_id, "delivery_attempt_id", 36)


def prepared_event_fingerprint(*, delivery_attempt_id: object, occurred_at: datetime, safe_payload: dict[str, object]) -> str:
    attempt_id = required_text(delivery_attempt_id, "delivery_attempt_id", 36)
    occurred = aware_utc(occurred_at, "occurred_at")
    if not isinstance(safe_payload, dict):
        raise OutreachError("INVALID_CONTRACT", "safe_payload must be an object")
    return sha256_fingerprint({
        "delivery_attempt_id": attempt_id,
        "event_type": DeliveryEventType.PREPARED.value,
        "occurred_at": occurred.isoformat(),
        "safe_payload": safe_payload,
        "sequence_number": 1,
    })


def outreach_delivery_mission_payload(delivery_attempt_id: object) -> dict[str, str]:
    """Freeze the future durable-ID-only M9C Mission payload shape."""
    return {"delivery_attempt_id": required_text(delivery_attempt_id, "delivery_attempt_id", 36)}


@dataclass(frozen=True)
class DeliveryPreparationResult:
    attempt: object
    event: object
    reused: bool
