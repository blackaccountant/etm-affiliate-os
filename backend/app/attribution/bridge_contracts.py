"""Privacy-bounded contracts for the M10A3 public attribution bridge."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.attribution.contracts import (
    AttributionIdempotencyConflict,
    aware_utc,
    canonical_fingerprint,
)


LINK_SOURCE_NAMESPACE = "m10a3.link"
CLICK_SOURCE_NAMESPACE = "m10a3.redirect"
CLICK_FACT_SOURCE_NAMESPACE = "m10a3.redirect.fact"
CONVERSION_FACT_SOURCE_NAMESPACE = "m10a3.conversion.fact"


class AttributionBridgeConflict(AttributionIdempotencyConflict):
    """An immutable public-bridge identity was reused with different content."""


def opaque_event_id(value: object | None) -> str:
    """Return a canonical opaque UUID, generating one when the caller supplies none."""
    if value is None:
        return str(uuid4())
    if isinstance(value, UUID):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = UUID(value.strip())
        except (AttributeError, ValueError) as exc:
            raise ValueError("Idempotency-Key must be an opaque UUID") from exc
    else:
        raise ValueError("Idempotency-Key must be an opaque UUID")
    if parsed.int == 0:
        raise ValueError("Idempotency-Key must not be the nil UUID")
    return str(parsed)


def bridge_digest(contract: str, payload: dict[str, object]) -> str:
    """Derive a persisted digest from bounded, non-PII bridge identity only."""
    return canonical_fingerprint(contract, payload)


def click_event_digest(event_id: object | None) -> tuple[str, str]:
    canonical = opaque_event_id(event_id)
    return canonical, bridge_digest("m10a3-redirect-event-v1", {"event_id": canonical})


def link_binding_digest(link_id: int, context_id: str) -> str:
    return bridge_digest(
        "m10a3-link-binding-source-v1",
        {"affiliate_link_id": link_id, "attribution_context_id": context_id},
    )


def click_fact_digest(event_digest: str) -> str:
    return bridge_digest(
        "m10a3-click-fact-source-v1",
        {"click_event_digest": event_digest},
    )


def conversion_fact_digest(conversion_id: int) -> str:
    return bridge_digest(
        "m10a3-conversion-fact-source-v1",
        {"affiliate_conversion_id": conversion_id},
    )


def legacy_utc(value: datetime | None, *, fallback: datetime | None = None) -> datetime:
    """Interpret legacy naive UTC timestamps without weakening new aware-UTC inputs."""
    candidate = value if value is not None else fallback
    if candidate is None:
        candidate = datetime.now(timezone.utc)
    if not isinstance(candidate, datetime):
        raise ValueError("legacy timestamp must be datetime")
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        return candidate.replace(tzinfo=timezone.utc)
    return aware_utc(candidate, "occurred_at")
