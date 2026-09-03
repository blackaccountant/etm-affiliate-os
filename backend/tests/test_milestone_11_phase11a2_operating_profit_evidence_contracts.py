from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timezone
from inspect import getsource
from types import SimpleNamespace

import pytest

from app.optimization.operating_profit_evidence_contracts import (
    OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION,
    OPERATING_PROFIT_EVIDENCE_SEMANTICS,
    OperatingProfitEvidenceRequest,
    OperatingProfitEvidenceRow,
)
from app.optimization.operating_profit_signal_contracts import (
    OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION,
    OPERATING_PROFIT_SIGNAL_SEMANTICS,
)
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


def test_version_and_semantics_are_frozen_measurement_metadata():
    assert OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION == "m11a2-operating-profit-evidence-v1"
    assert "no confidence" in OPERATING_PROFIT_EVIDENCE_SEMANTICS
    assert "no eligibility" in OPERATING_PROFIT_EVIDENCE_SEMANTICS


def test_request_delegates_m11a1_normalization():
    request = OperatingProfitEvidenceRequest(("earning", "affiliate_program"), " usd ").normalized()
    assert request.dimensions == ("affiliate_program", "earning") and request.currency == "USD"


@pytest.mark.parametrize("dimensions", [("earning", "earning"), ("unsupported",)])
def test_dimensions_fail_closed_through_m11a1(dimensions):
    with pytest.raises(ValueError): OperatingProfitEvidenceRequest(dimensions).normalized()


@pytest.mark.parametrize("currency", ["US", "USDD", "1$D"])
def test_currency_fails_closed_through_m11a1(currency):
    with pytest.raises(ValueError): OperatingProfitEvidenceRequest(currency=currency).normalized()


def test_row_is_frozen_with_exact_measurement_field_manifest():
    row = OperatingProfitEvidenceRow("USD", (("earning", 1),), 1, 1, 0, 1,
        datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc), "source", "source-v1")
    assert tuple(asdict(row)) == (
        "currency", "dimensions", "settled_earning_count", "settled_conversion_count",
        "attribution_click_count", "settlement_link_count", "first_settlement_observed_at",
        "latest_settlement_observed_at", "source_signal_semantics", "source_signal_contract_version",
        "evidence_semantics", "evidence_contract_version",
    )
    with pytest.raises(FrozenInstanceError): row.currency = "EUR"


def test_service_calls_m11a1_once_and_never_imports_financial_projection_services(monkeypatch):
    calls = []
    monkeypatch.setattr(OperatingProfitSignalService, "project", lambda service, request: calls.append(request) or ())
    service = OperatingProfitEvidenceService(SimpleNamespace())
    monkeypatch.setattr(service._settled_lineage, "settled_lineage", lambda **kwargs: ())
    monkeypatch.setattr(service._observations, "observed_at_by_settlement_link", lambda ids: ())
    assert service.project() == () and len(calls) == 1
    source = getsource(OperatingProfitEvidenceService)
    for forbidden in ("AttributionNetRealizedRevenueProjectionService", "AttributionContributionProfitProjectionService", "AttributionOperatingProfitProjectionService", ".commit(", ".rollback("):
        assert forbidden not in source


def test_deferred_policy_fields_are_absent_and_zero_click_is_valid():
    deferred = {"confidence", "eligibility", "rank", "recommendation", "sufficient_evidence", "freshness", "reason_code"}
    assert not deferred.intersection(OperatingProfitEvidenceRow.__dataclass_fields__)
    row = OperatingProfitEvidenceRow("USD", (), 1, 1, 0, 1,
        datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc),
        OPERATING_PROFIT_SIGNAL_SEMANTICS, OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION)
    assert row.attribution_click_count == 0
