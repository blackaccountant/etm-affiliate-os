"""Pure, provider-neutral M9C2B cold delivery contracts; no runtime execution."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.outreach.contracts import OutreachError, PreparedOutreachMessage, aware_utc, fingerprint, required_text, sha256_fingerprint
from app.outreach.cold_b2b_contracts import ColdRequestedAction, opaque_source_namespace


COLD_DELIVERY_OPERATION_SCHEMA_VERSION = "cold-delivery-operation-v1"
COLD_MESSAGE_CONTENT_SCHEMA_VERSION = "cold-message-content-v1"
COLD_T3_DECISION_SCHEMA_VERSION = "cold-t3-decision-v1"
_PROHIBITED_PERSISTED_KEYS = frozenset({"recipient", "recipient_email", "normalized_value", "destination", "body", "message_body", "provider_secret", "api_key", "secret"})
_RECIPIENT_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_RECIPIENT_PHONE = re.compile(r"(?<!\w)\+?\d[\d .()/-]{7,}\d(?!\w)")
_PERSONALIZATION_OR_SECRET = re.compile(r"(?i)\{\{|\}\}|\$\{|\b(?:recipient|recipient_email|to_email|destination|api[_-]?key|provider[_-]?secret|authorization|bearer|password|secret)\b")


def pii_bounded_payload(value: object) -> object:
    """Allow only compact internal facts; content and recipient routing stay elsewhere."""
    if value is None or isinstance(value, (bool, int, float)): return value
    if isinstance(value, str):
        if len(value) > 512 or "@" in value: raise OutreachError("PII_BOUNDARY_VIOLATION", "payload may not contain raw recipient or content")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 32: raise OutreachError("INVALID_CONTRACT", "payload list is too large")
        return [pii_bounded_payload(item) for item in value]
    if isinstance(value, dict):
        if len(value) > 32 or not all(isinstance(key, str) and 0 < len(key) <= 64 for key in value): raise OutreachError("INVALID_CONTRACT", "payload keys are invalid")
        if _PROHIBITED_PERSISTED_KEYS.intersection(key.lower() for key in value): raise OutreachError("PII_BOUNDARY_VIOLATION", "payload contains a prohibited field")
        return {key: pii_bounded_payload(item) for key, item in sorted(value.items())}
    raise OutreachError("INVALID_CONTRACT", "payload must be JSON-safe")


class ColdDeliveryState(str, Enum):
    CREATED = "CREATED"; READY = "READY"; T3_BLOCKED = "T3_BLOCKED"; DISPATCH_PLANNED = "DISPATCH_PLANNED"; PRE_SEND_BLOCKED = "PRE_SEND_BLOCKED"; DISPATCHING = "DISPATCHING"; ACCEPTED = "ACCEPTED"; REJECTED = "REJECTED"; TECHNICAL_RETRY_DUE = "TECHNICAL_RETRY_DUE"; RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"; UNRESOLVED_TERMINAL = "UNRESOLVED_TERMINAL"


_TRANSITIONS = {
    ColdDeliveryState.CREATED: {ColdDeliveryState.READY, ColdDeliveryState.T3_BLOCKED, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.READY: {ColdDeliveryState.DISPATCH_PLANNED, ColdDeliveryState.T3_BLOCKED, ColdDeliveryState.RECONCILIATION_REQUIRED, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.T3_BLOCKED: set(),
    ColdDeliveryState.DISPATCH_PLANNED: {ColdDeliveryState.PRE_SEND_BLOCKED, ColdDeliveryState.DISPATCHING, ColdDeliveryState.TECHNICAL_RETRY_DUE, ColdDeliveryState.RECONCILIATION_REQUIRED, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.DISPATCHING: {ColdDeliveryState.ACCEPTED, ColdDeliveryState.REJECTED, ColdDeliveryState.TECHNICAL_RETRY_DUE, ColdDeliveryState.RECONCILIATION_REQUIRED, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.ACCEPTED: set(), ColdDeliveryState.REJECTED: set(),
    ColdDeliveryState.TECHNICAL_RETRY_DUE: {ColdDeliveryState.DISPATCH_PLANNED, ColdDeliveryState.RECONCILIATION_REQUIRED, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.RECONCILIATION_REQUIRED: {ColdDeliveryState.ACCEPTED, ColdDeliveryState.REJECTED, ColdDeliveryState.TECHNICAL_RETRY_DUE, ColdDeliveryState.UNRESOLVED_TERMINAL},
    ColdDeliveryState.UNRESOLVED_TERMINAL: set(),
}


def validate_cold_delivery_transition(current: str, target: str) -> str:
    try: before, after = ColdDeliveryState(current), ColdDeliveryState(target)
    except (TypeError, ValueError) as exc: raise OutreachError("INVALID_COLD_DELIVERY_STATE", "unsupported cold delivery state") from exc
    if after not in _TRANSITIONS[before]: raise OutreachError("INVALID_COLD_DELIVERY_TRANSITION", f"{before.value} cannot transition to {after.value}")
    return after.value


@dataclass(frozen=True)
class CreateColdDeliveryOperationRequest:
    cold_authorization_id: str; lead_id: str; contact_point_id: str; action: str; purpose_key: str; source_namespace: str; source_event_key: str; message_content_fingerprint: str; created_at: datetime
    def __post_init__(self):
        for field in ("cold_authorization_id", "lead_id", "contact_point_id"): object.__setattr__(self, field, required_text(getattr(self, field), field, 36))
        object.__setattr__(self, "action", ColdRequestedAction(self.action).value)
        purpose = required_text(self.purpose_key, "purpose_key", 128)
        if not purpose.startswith("cold_b2b:"): raise OutreachError("INVALID_COLD_PURPOSE", "purpose_key must be cold_b2b")
        object.__setattr__(self, "purpose_key", purpose); object.__setattr__(self, "source_namespace", opaque_source_namespace(self.source_namespace)); object.__setattr__(self, "source_event_key", fingerprint(self.source_event_key, "source_event_key")); object.__setattr__(self, "message_content_fingerprint", fingerprint(self.message_content_fingerprint, "message_content_fingerprint")); object.__setattr__(self, "created_at", aware_utc(self.created_at, "created_at"))
    @property
    def purpose_family(self): return self.purpose_key.removeprefix("cold_b2b:")
    @property
    def request_fingerprint(self): return sha256_fingerprint({"action": self.action, "authorization_id": self.cold_authorization_id, "contact_point_id": self.contact_point_id, "lead_id": self.lead_id, "message_content_fingerprint": self.message_content_fingerprint, "purpose_key": self.purpose_key})


@dataclass(frozen=True)
class ColdMessageContentContract:
    message: PreparedOutreachMessage
    def __post_init__(self):
        if not isinstance(self.message, PreparedOutreachMessage): raise OutreachError("INVALID_CONTRACT", "message must use the bounded message contract")
        # Cold artifacts are reusable commercial copy, never personalized transport data.
        if self.message.channel_metadata:
            raise OutreachError("PII_BOUNDARY_VIOLATION", "cold message content may not carry channel metadata")
        validate_cold_message_text(self.message.subject, self.message.body)
    @property
    def content_fingerprint(self): return self.message.content_fingerprint


def validate_cold_message_text(subject: str | None, body: str) -> None:
    """Reject values that cannot be safely stored in a reusable cold artifact."""
    rendered = "\n".join(part for part in (subject, body) if part)
    if _RECIPIENT_EMAIL.search(rendered) or _RECIPIENT_PHONE.search(rendered) or _PERSONALIZATION_OR_SECRET.search(rendered):
        raise OutreachError("PII_BOUNDARY_VIOLATION", "cold message content may not contain recipient data, personalization, or provider secrets")


@dataclass(frozen=True)
class ColdT3DecisionContract:
    operation_id: str; cold_authorization_id: str; authorization_fingerprint: str; evaluated_at: datetime; policy_fingerprint: str; authority_fingerprint: str; crm_evidence_ids: tuple[str, ...]; recipient_fingerprint: str; decision: str; reason_codes: tuple[str, ...]
    def __post_init__(self):
        for field in ("operation_id", "cold_authorization_id"): object.__setattr__(self, field, required_text(getattr(self, field), field, 36))
        for field in ("authorization_fingerprint", "policy_fingerprint", "authority_fingerprint"): object.__setattr__(self, field, fingerprint(getattr(self, field), field))
        object.__setattr__(self, "evaluated_at", aware_utc(self.evaluated_at, "evaluated_at"))
        if self.decision not in {"ALLOWED", "BLOCKED"}: raise OutreachError("INVALID_T3_DECISION", "decision must be ALLOWED or BLOCKED")
        if self.decision == "ALLOWED": object.__setattr__(self, "recipient_fingerprint", fingerprint(self.recipient_fingerprint, "recipient_fingerprint"))
        elif self.recipient_fingerprint is not None: object.__setattr__(self, "recipient_fingerprint", fingerprint(self.recipient_fingerprint, "recipient_fingerprint"))
        object.__setattr__(self, "crm_evidence_ids", tuple(sorted({required_text(value, "crm_evidence_id", 36) for value in self.crm_evidence_ids})))
        object.__setattr__(self, "reason_codes", tuple(sorted({required_text(value, "reason_code", 64) for value in self.reason_codes})))
