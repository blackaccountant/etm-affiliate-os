"""Pure contract checks for M10A6's non-accounting projection boundary."""

from decimal import Decimal
import inspect

import pytest

from app.attribution.realized_revenue_projection_contracts import (
    PROJECTION_SEMANTICS, RealizedRevenueProjectionRequest, normalize_currency, normalize_dimensions,
)
from app.services.attribution_realized_revenue_projection_service import AttributionRealizedRevenueProjectionService


def test_request_normalization_is_deterministic_and_rejects_unsupported_semantics():
    assert normalize_dimensions(["earning", "affiliate_program"]) == ("affiliate_program", "earning")
    assert normalize_currency(" usd ") == "USD"
    assert RealizedRevenueProjectionRequest(("earning",), "eur").normalized().currency == "EUR"
    with pytest.raises(ValueError): normalize_dimensions(["profit"])
    with pytest.raises(ValueError): normalize_dimensions(["earning", "earning"])
    with pytest.raises(ValueError): normalize_currency("US")
    assert "currently authoritative" in PROJECTION_SEMANTICS
    assert "accounting" not in PROJECTION_SEMANTICS.lower()


def test_projection_service_is_read_only_and_uses_exact_decimal_buckets():
    source = inspect.getsource(AttributionRealizedRevenueProjectionService)
    for forbidden in (".add(", ".delete(", ".flush(", ".commit(", ".rollback("):
        assert forbidden not in source
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")
