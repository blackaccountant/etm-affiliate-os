from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal

import pytest

from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest, ContributionProfitProjectionRow


def test_default_request_is_frozen():
    request = ContributionProfitProjectionRequest()
    assert request.dimensions == () and request.currency is None
    with pytest.raises(FrozenInstanceError): request.currency = "USD"


def test_dimensions_reuse_frozen_normalization():
    assert ContributionProfitProjectionRequest(("earning", "affiliate_program")).normalized().dimensions == ("affiliate_program", "earning")


def test_duplicate_dimensions_fail_closed():
    with pytest.raises(ValueError): ContributionProfitProjectionRequest(("earning", "earning")).normalized()


def test_currency_normalizes_with_frozen_semantics():
    assert ContributionProfitProjectionRequest(currency=" usd ").normalized().currency == "USD"


def test_invalid_currency_fails_closed():
    with pytest.raises(ValueError): ContributionProfitProjectionRequest(currency="US").normalized()


def test_row_is_frozen_decimal_and_exactly_six_fields():
    row = ContributionProfitProjectionRow("USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"), (("earning", 1),))
    assert set(asdict(row)) == {"currency", "net_realized_commission", "directly_attributable_cost", "contribution_profit", "dimensions", "semantics"}
    assert all(isinstance(value, Decimal) for value in (row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit))
    with pytest.raises(FrozenInstanceError): row.currency = "EUR"
