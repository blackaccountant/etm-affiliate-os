"""Stable, provider-neutral contracts for durable distribution intent."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_SAFE_METADATA_KEYS = frozenset({"attempt", "platform_status", "provider_state"})


def _required_text(value: object, field: str, *, lowercase: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized.lower() if lowercase else normalized


def normalize_platform(value: object) -> str:
    """Return the canonical platform key used by durable distribution intent."""
    return _required_text(value, "platform", lowercase=True)


def _fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value.lower()):
        raise ValueError("payload_fingerprint must be a SHA-256 hex digest")
    return value.lower()


def canonicalize_prepared_content_body(value: object) -> str:
    """Preserve text exactly except for deterministic newline normalization."""
    if not isinstance(value, str):
        raise ValueError("prepared_content_body must be text")
    canonical = value.replace("\r\n", "\n").replace("\r", "\n")
    if not canonical.strip():
        raise ValueError("prepared_content_body is required")
    return canonical


def payload_fingerprint_for_body(prepared_content_body: object) -> str:
    canonical = canonicalize_prepared_content_body(prepared_content_body)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _json_safe(value: Any, field: str = "safe_metadata") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, field) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{field} keys must be text")
        return {key: _json_safe(item, field) for key, item in value.items()}
    raise ValueError(f"{field} must contain JSON-safe primitives")


def _safe_metadata(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("safe_metadata must be a JSON-safe object")
    unexpected = set(value).difference(_SAFE_METADATA_KEYS)
    if unexpected:
        raise ValueError("safe_metadata contains unsupported keys")
    return _json_safe(value)


def _serialized_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def distribution_correlation_key(distribution_run_id: object) -> str:
    """Derive the non-secret, immutable provider correlation key for one run."""
    return f"distribution:{_required_text(distribution_run_id, 'distribution_run_id')}"


class DistributionRunStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PUBLISHING = "PUBLISHING"
    RETRY_WAIT = "RETRY_WAIT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DistributionFailureCategory(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT_BEFORE_SUBMIT = "TIMEOUT_BEFORE_SUBMIT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INVALID_CONTENT = "INVALID_CONTENT"
    INVALID_DESTINATION = "INVALID_DESTINATION"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    AMBIGUOUS_SUBMIT_RESULT = "AMBIGUOUS_SUBMIT_RESULT"
    UNKNOWN_PERMANENT = "UNKNOWN_PERMANENT"

    @property
    def retryable(self) -> bool:
        return self in {
            DistributionFailureCategory.RATE_LIMIT,
            DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT,
            DistributionFailureCategory.PROVIDER_UNAVAILABLE,
        }


class DistributionStatusLookupState(str, Enum):
    PUBLISHED = "PUBLISHED"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DistributionAdapterMetadata:
    platform: str
    supports_status_lookup: bool
    supports_native_idempotency: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", normalize_platform(self.platform))
        if not isinstance(self.supports_status_lookup, bool):
            raise ValueError("supports_status_lookup must be boolean")
        if not isinstance(self.supports_native_idempotency, bool):
            raise ValueError("supports_native_idempotency must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "supports_status_lookup": self.supports_status_lookup,
            "supports_native_idempotency": self.supports_native_idempotency,
        }


@dataclass(frozen=True)
class CreateDistributionRunRequest:
    generated_content_artifact_id: str
    content_evaluation_id: str
    platform: str
    account_reference: str
    destination: str
    prepared_content_body: str | None = None
    scheduled_for: datetime | None = None


@dataclass(frozen=True)
class DistributionValidationRequest:
    distribution_run_id: str
    platform: str
    account_reference: str
    destination: str
    content_type: str | None = None
    payload_fingerprint: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "distribution_run_id", _required_text(self.distribution_run_id, "distribution_run_id"))
        object.__setattr__(self, "platform", normalize_platform(self.platform))
        object.__setattr__(self, "account_reference", _required_text(self.account_reference, "account_reference"))
        object.__setattr__(self, "destination", _required_text(self.destination, "destination"))
        object.__setattr__(self, "content_type", _optional_text(self.content_type, "content_type"))
        if self.payload_fingerprint is not None:
            object.__setattr__(self, "payload_fingerprint", _fingerprint(self.payload_fingerprint))

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_run_id": self.distribution_run_id,
            "platform": self.platform,
            "account_reference": self.account_reference,
            "destination": self.destination,
            "content_type": self.content_type,
            "payload_fingerprint": self.payload_fingerprint,
        }


@dataclass(frozen=True)
class DistributionValidationResult:
    valid: bool
    safe_message: str | None = None
    failure_category: DistributionFailureCategory | None = None
    normalized_destination: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise ValueError("valid must be boolean")
        object.__setattr__(self, "safe_message", _optional_text(self.safe_message, "safe_message"))
        if self.failure_category is not None:
            object.__setattr__(self, "failure_category", DistributionFailureCategory(self.failure_category))
        object.__setattr__(self, "normalized_destination", _optional_text(self.normalized_destination, "normalized_destination"))
        if self.valid and self.failure_category is not None:
            raise ValueError("valid result cannot include failure_category")
        if not self.valid and self.failure_category is None:
            raise ValueError("invalid result requires failure_category")

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "safe_message": self.safe_message,
            "failure_category": self.failure_category.value if self.failure_category else None,
            "normalized_destination": self.normalized_destination,
        }


@dataclass(frozen=True)
class DistributionPublishRequest:
    distribution_run_id: str
    generated_content_artifact_id: str
    content_evaluation_id: str
    platform: str
    account_reference: str
    destination: str
    payload_fingerprint: str
    content_body: str
    scheduled_for: datetime | None = None
    correlation_key: str | None = None

    def __post_init__(self) -> None:
        run_id = _required_text(self.distribution_run_id, "distribution_run_id")
        object.__setattr__(self, "distribution_run_id", run_id)
        object.__setattr__(self, "generated_content_artifact_id", _required_text(self.generated_content_artifact_id, "generated_content_artifact_id"))
        object.__setattr__(self, "content_evaluation_id", _required_text(self.content_evaluation_id, "content_evaluation_id"))
        object.__setattr__(self, "platform", normalize_platform(self.platform))
        object.__setattr__(self, "account_reference", _required_text(self.account_reference, "account_reference"))
        object.__setattr__(self, "destination", _required_text(self.destination, "destination"))
        object.__setattr__(self, "payload_fingerprint", _fingerprint(self.payload_fingerprint))
        object.__setattr__(self, "content_body", _required_text(self.content_body, "content_body"))
        if self.scheduled_for is not None:
            object.__setattr__(self, "scheduled_for", _aware_utc(self.scheduled_for, "scheduled_for"))
        correlation_key = distribution_correlation_key(run_id) if self.correlation_key is None else _required_text(self.correlation_key, "correlation_key")
        object.__setattr__(self, "correlation_key", correlation_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_run_id": self.distribution_run_id,
            "generated_content_artifact_id": self.generated_content_artifact_id,
            "content_evaluation_id": self.content_evaluation_id,
            "platform": self.platform,
            "account_reference": self.account_reference,
            "destination": self.destination,
            "payload_fingerprint": self.payload_fingerprint,
            "content_body": self.content_body,
            "scheduled_for": _serialized_datetime(self.scheduled_for),
            "correlation_key": self.correlation_key,
        }


@dataclass(frozen=True)
class DistributionPublishResult:
    success: bool
    external_post_id: str | None = None
    external_url: str | None = None
    published_at: datetime | None = None
    safe_metadata: dict[str, Any] | None = None
    failure_category: DistributionFailureCategory | None = None
    safe_message: str | None = None
    provider_idempotency_key: str | None = None
    provider_correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be boolean")
        for field in ("external_post_id", "external_url", "safe_message", "provider_idempotency_key", "provider_correlation_id"):
            object.__setattr__(self, field, _optional_text(getattr(self, field), field))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", _aware_utc(self.published_at, "published_at"))
        object.__setattr__(self, "safe_metadata", _safe_metadata(self.safe_metadata))
        if self.failure_category is not None:
            object.__setattr__(self, "failure_category", DistributionFailureCategory(self.failure_category))
        if self.success:
            if not self.external_post_id or not self.external_url or self.published_at is None:
                raise ValueError("successful publish result requires external ID, URL, and published_at")
            if self.failure_category is not None:
                raise ValueError("successful publish result cannot include failure_category")
        elif self.failure_category is None or self.safe_message is None:
            raise ValueError("failed publish result requires failure_category and safe_message")

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "external_post_id": self.external_post_id,
            "external_url": self.external_url,
            "published_at": _serialized_datetime(self.published_at),
            "safe_metadata": self.safe_metadata,
            "failure_category": self.failure_category.value if self.failure_category else None,
            "safe_message": self.safe_message,
            "provider_idempotency_key": self.provider_idempotency_key,
            "provider_correlation_id": self.provider_correlation_id,
        }


@dataclass(frozen=True)
class DistributionStatusRequest:
    distribution_run_id: str
    platform: str
    account_reference: str
    destination: str
    external_post_id: str | None = None
    correlation_key: str | None = None

    def __post_init__(self) -> None:
        run_id = _required_text(self.distribution_run_id, "distribution_run_id")
        object.__setattr__(self, "distribution_run_id", run_id)
        object.__setattr__(self, "platform", normalize_platform(self.platform))
        object.__setattr__(self, "account_reference", _required_text(self.account_reference, "account_reference"))
        object.__setattr__(self, "destination", _required_text(self.destination, "destination"))
        object.__setattr__(self, "external_post_id", _optional_text(self.external_post_id, "external_post_id"))
        correlation_key = distribution_correlation_key(run_id) if self.correlation_key is None else _required_text(self.correlation_key, "correlation_key")
        object.__setattr__(self, "correlation_key", correlation_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_run_id": self.distribution_run_id,
            "platform": self.platform,
            "account_reference": self.account_reference,
            "destination": self.destination,
            "external_post_id": self.external_post_id,
            "correlation_key": self.correlation_key,
        }


@dataclass(frozen=True)
class DistributionStatusResult:
    state: DistributionStatusLookupState
    external_post_id: str | None = None
    external_url: str | None = None
    published_at: datetime | None = None
    safe_metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", DistributionStatusLookupState(self.state))
        object.__setattr__(self, "external_post_id", _optional_text(self.external_post_id, "external_post_id"))
        object.__setattr__(self, "external_url", _optional_text(self.external_url, "external_url"))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", _aware_utc(self.published_at, "published_at"))
        object.__setattr__(self, "safe_metadata", _safe_metadata(self.safe_metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "external_post_id": self.external_post_id,
            "external_url": self.external_url,
            "published_at": _serialized_datetime(self.published_at),
            "safe_metadata": self.safe_metadata,
        }
