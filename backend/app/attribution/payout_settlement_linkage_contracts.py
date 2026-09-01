"""Privacy-bounded contracts for M10A5 payout settlement linkage."""

from __future__ import annotations

from app.attribution.contracts import AttributionIdempotencyConflict, canonical_fingerprint


SETTLEMENT_LINK_SOURCE_NAMESPACE = "m10a5.payout-settlement"


class AttributionPayoutSettlementLinkConflict(AttributionIdempotencyConflict):
    """A durable payout settlement identity conflicts with financial authority."""


def _positive_id(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _earning_link_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("attribution_earning_link_id is required")
    return value.strip()


def payout_settlement_link_digest(
    *,
    attribution_earning_link_id: str,
    affiliate_earning_id: int,
    affiliate_payout_id: int,
    affiliate_payout_attempt_id: int,
) -> str:
    """Produce a deterministic non-financial source identity for one settlement."""
    return canonical_fingerprint("m10a5-payout-settlement-source-v1", {
        "affiliate_earning_id": _positive_id(affiliate_earning_id, "affiliate_earning_id"),
        "affiliate_payout_attempt_id": _positive_id(
            affiliate_payout_attempt_id, "affiliate_payout_attempt_id",
        ),
        "affiliate_payout_id": _positive_id(affiliate_payout_id, "affiliate_payout_id"),
        "attribution_earning_link_id": _earning_link_id(attribution_earning_link_id),
    })


def payout_settlement_link_fingerprint(
    *,
    attribution_earning_link_id: str,
    affiliate_earning_id: int,
    affiliate_payout_id: int,
    affiliate_payout_attempt_id: int,
    source_namespace: str = SETTLEMENT_LINK_SOURCE_NAMESPACE,
    source_event_key_digest: str | None = None,
) -> str:
    digest = source_event_key_digest or payout_settlement_link_digest(
        attribution_earning_link_id=attribution_earning_link_id,
        affiliate_earning_id=affiliate_earning_id,
        affiliate_payout_id=affiliate_payout_id,
        affiliate_payout_attempt_id=affiliate_payout_attempt_id,
    )
    return canonical_fingerprint("m10a5-payout-settlement-v1", {
        "affiliate_earning_id": _positive_id(affiliate_earning_id, "affiliate_earning_id"),
        "affiliate_payout_attempt_id": _positive_id(
            affiliate_payout_attempt_id, "affiliate_payout_attempt_id",
        ),
        "affiliate_payout_id": _positive_id(affiliate_payout_id, "affiliate_payout_id"),
        "attribution_earning_link_id": _earning_link_id(attribution_earning_link_id),
        "source_event_key_digest": digest,
        "source_namespace": source_namespace,
    })
