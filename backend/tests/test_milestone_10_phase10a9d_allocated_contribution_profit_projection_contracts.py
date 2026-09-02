from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.attribution.allocated_contribution_profit_projection_contracts import (
    AllocatedContributionProfitProjectionRequest,
    AllocatedContributionProfitProjectionRow,
)
from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRow
from app.services.attribution_allocated_contribution_profit_projection_service import (
    AttributionAllocatedContributionProfitProjectionService,
)
from app.services.attribution_contribution_profit_projection_service import (
    AttributionContributionProfitProjectionService,
)


def test_default_request_is_frozen_and_reuses_frozen_normalization():
    request = AllocatedContributionProfitProjectionRequest(("earning", "affiliate_program"), " usd ").normalized()
    assert request.dimensions == ("affiliate_program", "earning") and request.currency == "USD"
    with pytest.raises(FrozenInstanceError):
        request.currency = "EUR"


@pytest.mark.parametrize("dimensions", [("earning", "earning"), ("unsupported",)])
def test_invalid_dimensions_fail_closed(dimensions):
    with pytest.raises(ValueError):
        AllocatedContributionProfitProjectionRequest(dimensions).normalized()


@pytest.mark.parametrize("currency", ["US", "USDD", "12$"])
def test_invalid_currency_fails_closed(currency):
    with pytest.raises(ValueError):
        AllocatedContributionProfitProjectionRequest(currency=currency).normalized()


def test_row_is_frozen_decimal_and_exactly_eight_fields():
    row = AllocatedContributionProfitProjectionRow(
        "USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"),
        Decimal("30.00"), Decimal("50.00"), (("earning", 1),),
    )
    assert set(asdict(row)) == {
        "currency", "net_realized_commission", "directly_attributable_cost", "contribution_profit",
        "allocated_shared_cost", "allocated_contribution_profit", "dimensions", "semantics",
    }
    assert all(isinstance(value, Decimal) for value in (
        row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit,
        row.allocated_shared_cost, row.allocated_contribution_profit,
    ))
    with pytest.raises(FrozenInstanceError):
        row.currency = "EUR"


def test_projection_composes_m10a9b_once_then_regroups_exact_decimal(monkeypatch):
    upstream = (
        ContributionProfitProjectionRow("USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"), (("affiliate_program", 7), ("earning", 1))),
        ContributionProfitProjectionRow("USD", Decimal("50.00"), Decimal("5.00"), Decimal("45.00"), (("affiliate_program", 7), ("earning", 2))),
    )
    calls = []

    def frozen_project(service, request):
        calls.append(request)
        return upstream

    monkeypatch.setattr(AttributionContributionProfitProjectionService, "project", frozen_project)
    service = AttributionAllocatedContributionProfitProjectionService(SimpleNamespace())
    monkeypatch.setattr(service.allocations, "finalized_allocations_for_earnings", lambda ids: (
        SimpleNamespace(earning=1, amount=Decimal("30.00"), currency="USD", cost_currency="USD", allocation_scope="shared"),
        SimpleNamespace(earning=2, amount=Decimal("10.00"), currency="USD", cost_currency="USD", allocation_scope="shared"),
    ))
    grouped = service.project(AllocatedContributionProfitProjectionRequest(("affiliate_program",)))
    earning_rows = service.project(AllocatedContributionProfitProjectionRequest(("earning",)))
    assert len(calls) == 1 and "earning" in calls[0].dimensions
    assert len(grouped) == 1
    assert (
        grouped[0].net_realized_commission,
        grouped[0].directly_attributable_cost,
        grouped[0].contribution_profit,
        grouped[0].allocated_shared_cost,
        grouped[0].allocated_contribution_profit,
    ) == (Decimal("150.00"), Decimal("25.00"), Decimal("125.00"), Decimal("40.00"), Decimal("85.00"))
    assert sum(row.allocated_contribution_profit for row in earning_rows) == grouped[0].allocated_contribution_profit


def test_inconsistent_or_cross_currency_allocation_fails_closed(monkeypatch):
    upstream = (ContributionProfitProjectionRow("USD", Decimal("100.00"), Decimal("0"), Decimal("100.00"), (("earning", 1),)),)
    monkeypatch.setattr(AttributionContributionProfitProjectionService, "project", lambda *args: upstream)
    service = AttributionAllocatedContributionProfitProjectionService(SimpleNamespace())
    for line in (
        SimpleNamespace(earning=1, amount=Decimal("10.00"), currency="USD", cost_currency="USD", allocation_scope="global"),
        SimpleNamespace(earning=1, amount=Decimal("10.00"), currency="EUR", cost_currency="EUR", allocation_scope="shared"),
    ):
        monkeypatch.setattr(service.allocations, "finalized_allocations_for_earnings", lambda ids, value=line: (value,))
        with pytest.raises(ValueError):
            service.project()
