from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.attribution.allocated_contribution_profit_projection_contracts import (
    AllocatedContributionProfitProjectionRow,
)
from app.attribution.operating_profit_projection_contracts import (
    OperatingProfitProjectionRequest,
    OperatingProfitProjectionRow,
)
from app.services.attribution_allocated_contribution_profit_projection_service import (
    AttributionAllocatedContributionProfitProjectionService,
)
from app.services.attribution_operating_profit_projection_service import (
    AttributionOperatingProfitProjectionService,
)


def test_request_is_frozen_and_reuses_frozen_normalization():
    request = OperatingProfitProjectionRequest(("earning", "affiliate_program"), " usd ").normalized()
    assert request.dimensions == ("affiliate_program", "earning") and request.currency == "USD"
    with pytest.raises(FrozenInstanceError):
        request.currency = "EUR"


@pytest.mark.parametrize("dimensions", [("earning", "earning"), ("unsupported",)])
def test_invalid_dimensions_fail_closed(dimensions):
    with pytest.raises(ValueError):
        OperatingProfitProjectionRequest(dimensions).normalized()


@pytest.mark.parametrize("currency", ["US", "USDD", "12$"])
def test_invalid_currency_fails_closed(currency):
    with pytest.raises(ValueError):
        OperatingProfitProjectionRequest(currency=currency).normalized()


def test_row_is_frozen_decimal_and_exactly_ten_fields():
    row = OperatingProfitProjectionRow(
        "USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"),
        Decimal("10.00"), Decimal("70.00"), Decimal("30.00"), Decimal("40.00"),
        (("earning", 1),),
    )
    assert set(asdict(row)) == {
        "currency", "net_realized_commission", "directly_attributable_cost",
        "contribution_profit", "allocated_shared_cost", "allocated_contribution_profit",
        "allocated_global_cost", "operating_profit", "dimensions", "semantics",
    }
    assert all(isinstance(value, Decimal) for value in (
        row.net_realized_commission, row.directly_attributable_cost,
        row.contribution_profit, row.allocated_shared_cost,
        row.allocated_contribution_profit, row.allocated_global_cost,
        row.operating_profit,
    ))
    with pytest.raises(FrozenInstanceError):
        row.currency = "EUR"


def test_projection_composes_m10a9d_once_and_regroups_exact_decimal(monkeypatch):
    upstream = (
        AllocatedContributionProfitProjectionRow("USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"), Decimal("10.00"), Decimal("70.00"), (("affiliate_program", 7), ("earning", 1))),
        AllocatedContributionProfitProjectionRow("USD", Decimal("50.00"), Decimal("5.00"), Decimal("45.00"), Decimal("20.00"), Decimal("25.00"), (("affiliate_program", 7), ("earning", 2))),
    )
    calls = []
    monkeypatch.setattr(
        AttributionAllocatedContributionProfitProjectionService,
        "project", lambda service, request: calls.append(request) or upstream,
    )
    service = AttributionOperatingProfitProjectionService(SimpleNamespace())
    monkeypatch.setattr(service.allocations, "finalized_global_allocations_for_earnings", lambda ids: (
        SimpleNamespace(earning=1, amount=Decimal("30.00"), currency="USD", cost_currency="USD", allocation_scope="global"),
        SimpleNamespace(earning=2, amount=Decimal("10.00"), currency="USD", cost_currency="USD", allocation_scope="global"),
    ))
    grouped = service.project(OperatingProfitProjectionRequest(("affiliate_program",)))
    earning_rows = service.project(OperatingProfitProjectionRequest(("earning",)))
    assert len(calls) == 1 and "earning" in calls[0].dimensions
    assert (grouped[0].allocated_contribution_profit, grouped[0].allocated_global_cost, grouped[0].operating_profit) == (
        Decimal("95.00"), Decimal("40.00"), Decimal("55.00"),
    )
    assert sum(row.operating_profit for row in earning_rows) == grouped[0].operating_profit


def test_currency_or_authority_contradiction_fails_closed_and_no_cost_only_rows(monkeypatch):
    upstream = (AllocatedContributionProfitProjectionRow("USD", Decimal("100"), Decimal("0"), Decimal("100"), Decimal("0"), Decimal("100"), (("earning", 1),)),)
    monkeypatch.setattr(AttributionAllocatedContributionProfitProjectionService, "project", lambda *args: upstream)
    service = AttributionOperatingProfitProjectionService(SimpleNamespace())
    for line in (
        SimpleNamespace(earning=1, amount=Decimal("10"), currency="EUR", cost_currency="EUR", allocation_scope="global"),
        SimpleNamespace(earning=1, amount=Decimal("10"), currency="USD", cost_currency="USD", allocation_scope="shared"),
    ):
        monkeypatch.setattr(service.allocations, "finalized_global_allocations_for_earnings", lambda ids, value=line: (value,))
        with pytest.raises(ValueError):
            service.project()
    fresh = AttributionOperatingProfitProjectionService(SimpleNamespace())
    monkeypatch.setattr(AttributionAllocatedContributionProfitProjectionService, "project", lambda *args: upstream)
    monkeypatch.setattr(fresh.allocations, "finalized_global_allocations_for_earnings", lambda ids: ())
    assert fresh.project()[0].allocated_global_cost == Decimal("0")
