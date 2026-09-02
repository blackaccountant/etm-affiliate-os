from decimal import Decimal
import inspect
import pytest
from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest, normalize_currency
from app.services.attribution_net_realized_revenue_projection_service import AttributionNetRealizedRevenueProjectionService
from types import SimpleNamespace
from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest

def test_contract_is_currency_scoped_and_read_only():
    assert NetRealizedRevenueProjectionRequest(("earning",), " usd ").normalized().currency == "USD"
    with pytest.raises(ValueError): normalize_currency("US")
    source=inspect.getsource(AttributionNetRealizedRevenueProjectionService)
    for forbidden in (".add(",".delete(",".flush(",".commit(",".rollback("): assert forbidden not in source
    assert Decimal("100.00") + Decimal("-20.00") + Decimal("10.00") == Decimal("90.00")

def test_projection_math_zero_visibility_grouping_and_negative_integrity(monkeypatch):
    service=AttributionNetRealizedRevenueProjectionService(SimpleNamespace())
    rows=[SimpleNamespace(earning=1,currency="USD",commission_amount=Decimal("100.00"),affiliate_program=7,product=8,content_asset=None,attribution_publication=None,publishing_authority=None,distribution_run=None,affiliate_link=None,attribution_context=None,attribution_click=None,conversion=2,settlement_link="s")]
    monkeypatch.setattr(service.settled,"settled_lineage",lambda **_:rows)
    monkeypatch.setattr(service.adjustments,"adjustments_by_settled_lineage",lambda _: {1:Decimal("-100.00")})
    result=service.project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD"));assert result[0].net_realized_commission==Decimal("0") and result[0].dimensions==(("affiliate_program",7),("earning",1))
    monkeypatch.setattr(service.adjustments,"adjustments_by_settled_lineage",lambda _: {1:Decimal("-100.01")})
    with pytest.raises(ValueError,match="negative net"): service.project()
