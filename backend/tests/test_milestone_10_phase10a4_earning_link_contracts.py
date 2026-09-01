"""Pure contract proofs for the narrow M10A4 earning-link bridge."""

import inspect
from datetime import timezone

import pytest

from app.attribution.earning_linkage_contracts import (
    EARNING_LINK_SOURCE_NAMESPACE,
    earning_link_digest,
    earning_link_fingerprint,
)
from app.models.attribution_earning_link import AttributionEarningLink
from app.services.attribution_earning_link_service import AttributionEarningLinkService


def test_earning_link_identity_is_deterministic_versioned_and_bounded():
    first = earning_link_digest(
        attribution_fact_id="fact-1", affiliate_conversion_id=1, affiliate_earning_id=2,
    )
    assert first == earning_link_digest(
        attribution_fact_id="fact-1", affiliate_conversion_id=1, affiliate_earning_id=2,
    )
    assert first != earning_link_digest(
        attribution_fact_id="fact-2", affiliate_conversion_id=1, affiliate_earning_id=2,
    )
    assert len(first) == 64
    assert earning_link_fingerprint(
        attribution_fact_id="fact-1", affiliate_conversion_id=1, affiliate_earning_id=2,
    ) != first
    for invalid in (0, -1, True, "1"):
        with pytest.raises(ValueError):
            earning_link_digest(
                attribution_fact_id="fact-1", affiliate_conversion_id=invalid, affiliate_earning_id=2,
            )


def test_linkage_model_contains_only_reference_integrity_material_and_aware_utc():
    names = {column.name for column in AttributionEarningLink.__table__.columns}
    assert names == {
        "id", "attribution_fact_id", "affiliate_conversion_id", "affiliate_earning_id",
        "source_namespace", "source_event_key_digest", "linkage_fingerprint",
        "observed_at", "recorded_at",
    }
    forbidden = {
        "sale_amount", "commission_amount", "commission_rate", "gross_amount", "currency",
        "status", "payout_reference", "customer_reference", "metadata_json", "provider_reference",
    }
    assert not names & forbidden
    assert AttributionEarningLink.__table__.c.observed_at.type.timezone is True
    assert AttributionEarningLink.__table__.c.recorded_at.type.timezone is True
    assert EARNING_LINK_SOURCE_NAMESPACE == "m10a4.earning-link"


def test_service_owns_the_outer_transaction_and_never_mutates_financial_models():
    source = inspect.getsource(AttributionEarningLinkService)
    assert ".commit(" in source and ".rollback(" in source
    for forbidden in ("AffiliateConversion(", "AffiliateEarning(", "AffiliatePayout(", "AffiliatePayoutAttempt("):
        assert forbidden not in source
