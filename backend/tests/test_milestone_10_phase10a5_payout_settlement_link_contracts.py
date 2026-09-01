"""Pure contract proofs for the narrow M10A5 settlement observation."""

import inspect
from datetime import timezone

import pytest

from app.attribution.payout_settlement_linkage_contracts import (
    SETTLEMENT_LINK_SOURCE_NAMESPACE,
    payout_settlement_link_digest,
    payout_settlement_link_fingerprint,
)
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService


def test_settlement_identity_is_deterministic_versioned_and_bounded():
    first = payout_settlement_link_digest(
        attribution_earning_link_id="earning-link-1", affiliate_earning_id=2,
        affiliate_payout_id=3, affiliate_payout_attempt_id=4,
    )
    assert first == payout_settlement_link_digest(
        attribution_earning_link_id="earning-link-1", affiliate_earning_id=2,
        affiliate_payout_id=3, affiliate_payout_attempt_id=4,
    )
    assert first != payout_settlement_link_digest(
        attribution_earning_link_id="earning-link-1", affiliate_earning_id=2,
        affiliate_payout_id=3, affiliate_payout_attempt_id=5,
    )
    assert len(first) == 64
    assert payout_settlement_link_fingerprint(
        attribution_earning_link_id="earning-link-1", affiliate_earning_id=2,
        affiliate_payout_id=3, affiliate_payout_attempt_id=4,
    ) != first
    for invalid in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            payout_settlement_link_digest(
                attribution_earning_link_id="earning-link-1", affiliate_earning_id=invalid,
                affiliate_payout_id=3, affiliate_payout_attempt_id=4,
            )


def test_model_is_reference_only_and_uses_aware_utc():
    names = {column.name for column in AttributionPayoutSettlementLink.__table__.columns}
    assert names == {
        "id", "attribution_earning_link_id", "affiliate_earning_id", "affiliate_payout_id",
        "affiliate_payout_attempt_id", "source_namespace", "source_event_key_digest",
        "linkage_fingerprint", "observed_at", "recorded_at",
    }
    forbidden = {
        "sale_amount", "gross_amount", "commission_amount", "commission_rate", "total_amount",
        "currency", "status", "payout_reference", "provider", "provider_reference",
        "failure_reason", "customer_reference", "metadata_json", "bank_account",
    }
    assert not names & forbidden
    assert AttributionPayoutSettlementLink.__table__.c.observed_at.type.timezone is True
    assert AttributionPayoutSettlementLink.__table__.c.recorded_at.type.timezone is True
    assert SETTLEMENT_LINK_SOURCE_NAMESPACE == "m10a5.payout-settlement"


def test_service_owns_its_transaction_and_does_not_construct_financial_records():
    source = inspect.getsource(AttributionPayoutSettlementLinkService)
    assert ".commit(" in source and ".rollback(" in source
    for forbidden in (
        "AffiliateConversion(", "AffiliateEarning(", "AffiliatePayout(",
        "AffiliatePayoutAttempt(", "AttributionEarningLink(",
    ):
        assert forbidden not in source
