"""Deterministic, privacy-bounded contracts for the M10A attribution spine."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, uuid5


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_NAMESPACE = re.compile(r"^[a-z][a-z0-9.-]{0,62}$", re.ASCII)


class AttributionContractError(ValueError):
    """Raised when attribution input violates a stable public contract."""


class AttributionIdempotencyConflict(AttributionContractError):
    """A source identity was reused with different immutable content."""


class AttributionFactKind(str, Enum):
    PUBLICATION_BOUND = "PUBLICATION_BOUND"
    LINK_BOUND = "LINK_BOUND"
    CLICK_RECORDED = "CLICK_RECORDED"
    CONVERSION_REPORTED = "CONVERSION_REPORTED"
    ATTRIBUTION_CORRECTED = "ATTRIBUTION_CORRECTED"


def required_text(value: object, field: str, *, maximum: int, lowercase: bool = False) -> str:
    if not isinstance(value, str):
        raise AttributionContractError(f"{field} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise AttributionContractError(f"{field} is required")
    if len(normalized) > maximum:
        raise AttributionContractError(f"{field} exceeds {maximum} characters")
    return normalized.lower() if lowercase else normalized


def source_identity(namespace: object, event_key_digest: object) -> tuple[str, str]:
    if not isinstance(namespace, str):
        raise AttributionContractError("source_namespace must be text")
    normalized_namespace = namespace.strip().lower()
    if not _SOURCE_NAMESPACE.fullmatch(normalized_namespace):
        raise AttributionContractError(
            "source_namespace must match ^[a-z][a-z0-9.-]{0,62}$"
        )
    return normalized_namespace, validate_fingerprint(
        event_key_digest, "source_event_key_digest"
    )


def aware_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AttributionContractError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def validate_fingerprint(value: object, field: str = "source_fingerprint") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise AttributionContractError(f"{field} must be 64 lowercase hexadecimal characters")
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise AttributionContractError("canonical JSON keys must be text")
        return {key: _json_safe(item) for key, item in value.items()}
    raise AttributionContractError("canonical JSON accepts only JSON-safe primitives")


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            _json_safe(value), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    except ValueError as exc:
        raise AttributionContractError(
            "canonical JSON does not allow non-finite numbers"
        ) from exc


def canonical_fingerprint(contract_version: object, payload: Any) -> str:
    version = required_text(contract_version, "contract_version", maximum=128, lowercase=True)
    material = canonical_json({"contract": version, "payload": _json_safe(payload)})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def context_fingerprint(*, affiliate_program_id: int, attribution_publication_id: str) -> str:
    if not isinstance(affiliate_program_id, int) or affiliate_program_id < 1:
        raise AttributionContractError("affiliate_program_id must be a positive integer")
    publication_id = required_text(attribution_publication_id, "attribution_publication_id", maximum=36)
    return canonical_fingerprint(
        "attribution-context-v1",
        {"affiliate_program_id": affiliate_program_id, "attribution_publication_id": publication_id},
    )


def click_key_for_source(source_namespace: str, source_event_key_digest: str) -> str:
    namespace, digest = source_identity(source_namespace, source_event_key_digest)
    return str(uuid5(NAMESPACE_URL, canonical_json({
        "contract": "attribution-click-key-v1",
        "source_event_key_digest": digest,
        "source_namespace": namespace,
    })))


def click_fingerprint(*, click_key: str, attribution_context_id: str, affiliate_link_id: int,
                      source_namespace: str, source_event_key_digest: str,
                      occurred_at: datetime) -> str:
    namespace, digest = source_identity(source_namespace, source_event_key_digest)
    occurred = aware_utc(occurred_at, "occurred_at")
    return canonical_fingerprint("attribution-click-v1", {
        "affiliate_link_id": affiliate_link_id,
        "attribution_context_id": required_text(attribution_context_id, "attribution_context_id", maximum=36),
        "click_key": required_text(click_key, "click_key", maximum=64),
        "occurred_at": occurred.isoformat(),
        "source_event_key_digest": digest,
        "source_namespace": namespace,
    })


def fact_references(*, fact_kind: object, attribution_publication_id: str | None = None,
                    attribution_context_id: str | None = None, attribution_click_id: str | None = None,
                    affiliate_link_id: int | None = None, affiliate_conversion_id: int | None = None,
                    supersedes_fact_id: str | None = None) -> dict[str, object | None]:
    try:
        kind = AttributionFactKind(fact_kind)
    except (TypeError, ValueError) as exc:
        raise AttributionContractError("unsupported attribution fact kind") from exc
    refs = {
        "attribution_publication_id": attribution_publication_id,
        "attribution_context_id": attribution_context_id,
        "attribution_click_id": attribution_click_id,
        "affiliate_link_id": affiliate_link_id,
        "affiliate_conversion_id": affiliate_conversion_id,
        "supersedes_fact_id": supersedes_fact_id,
    }
    required = {
        AttributionFactKind.PUBLICATION_BOUND: {"attribution_publication_id"},
        AttributionFactKind.LINK_BOUND: {"attribution_context_id", "affiliate_link_id"},
        AttributionFactKind.CLICK_RECORDED: {"attribution_context_id", "attribution_click_id", "affiliate_link_id"},
        AttributionFactKind.CONVERSION_REPORTED: {"attribution_context_id", "affiliate_conversion_id"},
        AttributionFactKind.ATTRIBUTION_CORRECTED: {"supersedes_fact_id"},
    }[kind]
    missing = [field for field in required if refs[field] is None]
    if missing:
        raise AttributionContractError(f"{kind.value} requires {', '.join(sorted(missing))}")
    forbidden = {
        AttributionFactKind.PUBLICATION_BOUND: set(refs) - {"attribution_publication_id"},
        AttributionFactKind.LINK_BOUND: set(refs) - {"attribution_context_id", "affiliate_link_id"},
        AttributionFactKind.CLICK_RECORDED: set(refs) - {"attribution_context_id", "attribution_click_id", "affiliate_link_id"},
        AttributionFactKind.CONVERSION_REPORTED: {"attribution_publication_id", "supersedes_fact_id"},
        AttributionFactKind.ATTRIBUTION_CORRECTED: set(),
    }[kind]
    present_forbidden = [field for field in forbidden if refs[field] is not None]
    if present_forbidden:
        raise AttributionContractError(f"{kind.value} does not allow {', '.join(sorted(present_forbidden))}")
    return {"fact_kind": kind.value, **refs}


def fact_fingerprint(*, fact_kind: object, source_namespace: str, source_event_key_digest: str,
                     occurred_at: datetime, **references: object) -> str:
    namespace, digest = source_identity(source_namespace, source_event_key_digest)
    occurred = aware_utc(occurred_at, "occurred_at")
    refs = fact_references(fact_kind=fact_kind, **references)
    return canonical_fingerprint("attribution-fact-v1", {
        **refs,
        "occurred_at": occurred.isoformat(),
        "source_event_key_digest": digest,
        "source_namespace": namespace,
    })
