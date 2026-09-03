from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal
from inspect import getsource
from types import SimpleNamespace

import pytest

from app.attribution.operating_profit_projection_contracts import (
    OPERATING_PROFIT_PROJECTION_SEMANTICS,
    OperatingProfitProjectionRow,
)
from app.optimization.operating_profit_signal_contracts import (
    OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION,
    OPERATING_PROFIT_SIGNAL_SEMANTICS,
    OperatingProfitSignalRequest,
    OperatingProfitSignalRow,
)
from app.services.attribution_operating_profit_projection_service import (
    AttributionOperatingProfitProjectionService,
)
from app.services.operating_profit_signal_service import OperatingProfitSignalService


def _upstream(*, operating_profit=Decimal("40.00"), source_semantics=OPERATING_PROFIT_PROJECTION_SEMANTICS):
    return OperatingProfitProjectionRow(
        "USD", Decimal("100.00"), Decimal("20.00"), Decimal("80.00"),
        Decimal("10.00"), Decimal("70.00"), Decimal("30.00"), operating_profit,
        (("affiliate_program", 7), ("earning", 1)), source_semantics,
    )


def test_constants_are_stable_consumer_metadata():
    assert OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION == "m11a1-operating-profit-signal-v1"
    assert "read-only" in OPERATING_PROFIT_SIGNAL_SEMANTICS
    assert "M10A9F" in OPERATING_PROFIT_SIGNAL_SEMANTICS


def test_request_delegates_frozen_m10_normalization():
    request = OperatingProfitSignalRequest(("earning", "affiliate_program"), " usd ").normalized()
    assert request.dimensions == ("affiliate_program", "earning")
    assert request.currency == "USD"


@pytest.mark.parametrize("dimensions", [("earning", "earning"), ("not-a-dimension",)])
def test_invalid_dimensions_fail_closed_through_m10(dimensions):
    with pytest.raises(ValueError):
        OperatingProfitSignalRequest(dimensions).normalized()


@pytest.mark.parametrize("currency", ["US", "USDD", "1$D"])
def test_invalid_currency_fails_closed_through_m10(currency):
    with pytest.raises(ValueError):
        OperatingProfitSignalRequest(currency=currency).normalized()


def test_signal_row_is_frozen_and_has_exact_field_manifest():
    row = OperatingProfitSignalRow(
        "USD", Decimal("100"), Decimal("20"), Decimal("80"), Decimal("10"),
        Decimal("70"), Decimal("30"), Decimal("40"), (("earning", 1),), "upstream",
    )
    assert tuple(asdict(row)) == (
        "currency", "net_realized_commission", "directly_attributable_cost",
        "contribution_profit", "allocated_shared_cost", "allocated_contribution_profit",
        "allocated_global_cost", "operating_profit", "dimensions", "source_semantics",
        "signal_semantics", "signal_contract_version",
    )
    with pytest.raises(FrozenInstanceError):
        row.currency = "EUR"


def test_service_composes_m10a9f_once_and_copies_all_values(monkeypatch):
    calls = []
    monkeypatch.setattr(
        AttributionOperatingProfitProjectionService,
        "project", lambda service, request: calls.append(request) or (_upstream(),),
    )
    signals = OperatingProfitSignalService(SimpleNamespace()).project(
        OperatingProfitSignalRequest(("earning",), "USD"),
    )
    assert len(calls) == 1 and calls[0].dimensions == ("earning",) and calls[0].currency == "USD"
    signal = signals[0]
    upstream = _upstream()
    assert all(getattr(signal, name) == getattr(upstream, name) for name in (
        "currency", "net_realized_commission", "directly_attributable_cost", "contribution_profit",
        "allocated_shared_cost", "allocated_contribution_profit", "allocated_global_cost",
        "operating_profit", "dimensions",
    ))
    assert signal.source_semantics == OPERATING_PROFIT_PROJECTION_SEMANTICS
    assert signal.signal_semantics == OPERATING_PROFIT_SIGNAL_SEMANTICS
    assert signal.signal_contract_version == OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION


@pytest.mark.parametrize("value", [Decimal("0.00"), Decimal("-20.00")])
def test_zero_and_negative_operating_profit_are_preserved(monkeypatch, value):
    monkeypatch.setattr(AttributionOperatingProfitProjectionService, "project", lambda *args: (_upstream(operating_profit=value),))
    signal = OperatingProfitSignalService(SimpleNamespace()).project()[0]
    assert signal.operating_profit == value


def test_source_semantics_is_copied_without_m11_interpretation(monkeypatch):
    expected = "frozen upstream semantics are opaque to M11"
    monkeypatch.setattr(
        AttributionOperatingProfitProjectionService,
        "project", lambda *args: (_upstream(source_semantics=expected),),
    )
    assert OperatingProfitSignalService(SimpleNamespace()).project()[0].source_semantics == expected


def test_service_has_no_lower_financial_authority_or_sql_dependency():
    source = getsource(OperatingProfitSignalService)
    assert "self._operating_profit.project" in source
    for forbidden in (
        "Repository", "AttributionNetRealizedRevenueProjectionService",
        "AttributionContributionProfitProjectionService",
        "AttributionAllocatedContributionProfitProjectionService",
        "AffiliateCost", ".query(", ".execute(", ".commit(", ".rollback(",
    ):
        assert forbidden not in source


def test_deferred_decision_fields_are_absent():
    deferred = {
        "confidence", "freshness", "eligibility", "sample_size", "score", "rank",
        "recommendation", "roi", "margin", "decision_policy", "action", "budget",
        "experiment_assignment",
    }
    assert not deferred.intersection(OperatingProfitSignalRow.__dataclass_fields__)
