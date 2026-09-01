"""Privacy-bounded contracts for M10A4 attribution earning linkage."""

from __future__ import annotations

from app.attribution.contracts import AttributionIdempotencyConflict, canonical_fingerprint


EARNING_LINK_SOURCE_NAMESPACE = "m10a4.earning-link"


class AttributionEarningLinkConflict(AttributionIdempotencyConflict):
    """A durable earning-link identity conflicts with authoritative records."""


def _positive_id(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def earning_link_digest(
    *, attribution_fact_id: str, affiliate_conversion_id: int, affiliate_earning_id: int,
) -> str:
    if not isinstance(attribution_fact_id, str) or not attribution_fact_id.strip():
        raise ValueError("attribution_fact_id is required")
    return canonical_fingerprint("m10a4-earning-link-source-v1", {
        "affiliate_conversion_id": _positive_id(affiliate_conversion_id, "affiliate_conversion_id"),
        "affiliate_earning_id": _positive_id(affiliate_earning_id, "affiliate_earning_id"),
        "attribution_fact_id": attribution_fact_id.strip(),
    })


def earning_link_fingerprint(
    *, attribution_fact_id: str, affiliate_conversion_id: int, affiliate_earning_id: int,
    source_namespace: str = EARNING_LINK_SOURCE_NAMESPACE,
    source_event_key_digest: str | None = None,
) -> str:
    digest = source_event_key_digest or earning_link_digest(
        attribution_fact_id=attribution_fact_id,
        affiliate_conversion_id=affiliate_conversion_id,
        affiliate_earning_id=affiliate_earning_id,
    )
    return canonical_fingerprint("m10a4-earning-link-v1", {
        "affiliate_conversion_id": _positive_id(affiliate_conversion_id, "affiliate_conversion_id"),
        "affiliate_earning_id": _positive_id(affiliate_earning_id, "affiliate_earning_id"),
        "attribution_fact_id": attribution_fact_id.strip(),
        "source_event_key_digest": digest,
        "source_namespace": source_namespace,
    })
