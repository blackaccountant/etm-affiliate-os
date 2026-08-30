"""Immutable contracts for M8C qualification linking and Lead lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.crm.contracts import CRMError, aware_utc, enum_value, required_text


class LeadLifecycleState(str, Enum):
    DISCOVERED = "DISCOVERED"
    ENRICHED = "ENRICHED"
    QUALIFIED = "QUALIFIED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    ARCHIVED = "ARCHIVED"


class LifecycleError(CRMError):
    """Safe typed rejection from the M8C lifecycle boundary."""


@dataclass(frozen=True)
class LifecycleTransitionRequest:
    to_state: str
    occurred_at: datetime
    source_namespace: str
    source_event_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "to_state", enum_value(self.to_state, LeadLifecycleState, "to_state"))
        object.__setattr__(self, "occurred_at", aware_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "source_namespace", required_text(self.source_namespace, "source_namespace", 100))
        object.__setattr__(self, "source_event_key", required_text(self.source_event_key, "source_event_key", 512))

    def fingerprint_for(self, lead_id: str) -> str:
        payload = {
            "lead_id": required_text(lead_id, "lead_id", 36),
            "to_state": self.to_state,
            "occurred_at": self.occurred_at.isoformat(),
            "source_namespace": self.source_namespace,
            "source_event_key": self.source_event_key,
        }
        encoded = json.dumps(
            {"namespace": "crm-lead-lifecycle-event-v1", "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LifecycleTransitionDecision:
    from_state: str | None
    to_state: str


@dataclass(frozen=True)
class LeadQualificationLinkResult:
    link_id: str
    reused: bool


@dataclass(frozen=True)
class LifecycleTransitionResult:
    event_id: str
    reused: bool
    sequence_number: int
    effective_state: str
