"""Provider-neutral, PII-bounded contracts for M9C1 outreach delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Protocol

from app.outreach.contracts import OutreachError, required_text, sha256_fingerprint


RESEND_PROVIDER_KEY = "resend"
RESEND_CONTRACT_VERSION = "resend-email-v1"
RESEND_DOCUMENTED_IDEMPOTENCY_HOURS = 24
RESEND_SAFE_REPLAY_HOURS = 23


class ProviderSendOutcome(str, Enum):
    DEFINITELY_ACCEPTED = "DEFINITELY_ACCEPTED"
    DEFINITELY_REJECTED = "DEFINITELY_REJECTED"
    AMBIGUOUS = "AMBIGUOUS"


class ProviderFailureCategory(str, Enum):
    TRANSIENT_BEFORE_SIDE_EFFECT = "TRANSIENT_BEFORE_SIDE_EFFECT"
    DETERMINISTIC_REJECTION = "DETERMINISTIC_REJECTION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    AMBIGUOUS_SIDE_EFFECT = "AMBIGUOUS_SIDE_EFFECT"
    CONFIGURATION_AUTHENTICATION = "CONFIGURATION_AUTHENTICATION"


@dataclass(frozen=True)
class ProviderCapabilities:
    provider_key: str
    provider_contract_version: str
    channels: tuple[str, ...]
    native_idempotency: bool
    documented_idempotency_retention: timedelta
    safe_replay_horizon: timedelta
    supports_provider_reference: bool


@dataclass(frozen=True, repr=False)
class EphemeralRecipient:
    """Routing data that must never cross the in-memory provider boundary."""

    channel: str
    value: str

    def __post_init__(self) -> None:
        if self.channel != "EMAIL":
            raise OutreachError("UNSUPPORTED_CHANNEL", "M9C1 supports EMAIL only")
        value = required_text(self.value, "recipient", 320)
        if value.count("@") != 1 or any(char.isspace() for char in value):
            raise OutreachError("INVALID_RECIPIENT", "email routing representation is invalid")
        local, domain = value.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise OutreachError("INVALID_RECIPIENT", "email routing representation is invalid")
        object.__setattr__(self, "value", value)

    def __repr__(self) -> str:
        return "EphemeralRecipient(channel='EMAIL', value=<redacted>)"


@dataclass(frozen=True, repr=False)
class ProviderSendRequest:
    operation_key: str
    sender: str
    recipient: EphemeralRecipient
    subject: str | None
    body: str
    content_format: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_key", required_text(self.operation_key, "operation_key", 255))
        object.__setattr__(self, "sender", required_text(self.sender, "sender", 998))
        if not isinstance(self.recipient, EphemeralRecipient):
            raise OutreachError("INVALID_CONTRACT", "recipient must be ephemeral")
        if self.content_format not in {"TEXT", "HTML"}:
            raise OutreachError("INVALID_CONTRACT", "unsupported provider content format")
        if not isinstance(self.body, str) or not self.body.strip():
            raise OutreachError("INVALID_CONTRACT", "provider body is required")

    def __repr__(self) -> str:
        return f"ProviderSendRequest(operation_key={self.operation_key!r}, payload=<redacted>)"

    @property
    def sender_identity_fingerprint(self) -> str:
        return sha256_fingerprint({"sender": self.sender})

    @property
    def provider_payload_fingerprint(self) -> str:
        return sha256_fingerprint({
            "from": self.sender,
            "to": self.recipient.value,
            "subject": self.subject,
            "text" if self.content_format == "TEXT" else "html": self.body,
            "tags": [],
        })


@dataclass(frozen=True)
class ProviderFailure:
    category: ProviderFailureCategory
    safe_code: str

    @property
    def retryable(self) -> bool:
        return self.category is ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT


@dataclass(frozen=True)
class ProviderSendResult:
    outcome: ProviderSendOutcome | None
    provider_reference: str | None = None
    failure: ProviderFailure | None = None

    def __post_init__(self) -> None:
        if self.outcome is ProviderSendOutcome.DEFINITELY_ACCEPTED:
            reference = required_text(self.provider_reference, "provider_reference", 255)
            object.__setattr__(self, "provider_reference", reference)
        elif self.provider_reference is not None:
            raise OutreachError("INVALID_PROVIDER_RESULT", "only acceptance may carry a provider reference")
        if self.outcome is None and self.failure is None:
            raise OutreachError("INVALID_PROVIDER_RESULT", "provider result has no outcome")


class OutreachProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    @property
    def sender_identity(self) -> str: ...

    def send(self, request: ProviderSendRequest) -> ProviderSendResult: ...


def provider_operation_key(delivery_attempt_id: object) -> str:
    attempt_id = required_text(delivery_attempt_id, "delivery_attempt_id", 36)
    return f"outreach-delivery/{attempt_id}/{RESEND_CONTRACT_VERSION}"


def provider_operation_fingerprint(delivery_attempt_id: object, operation_key: object) -> str:
    return sha256_fingerprint({
        "delivery_attempt_id": required_text(delivery_attempt_id, "delivery_attempt_id", 36),
        "provider_contract_version": RESEND_CONTRACT_VERSION,
        "provider_key": RESEND_PROVIDER_KEY,
        "provider_operation_key": required_text(operation_key, "provider_operation_key", 255),
    })
