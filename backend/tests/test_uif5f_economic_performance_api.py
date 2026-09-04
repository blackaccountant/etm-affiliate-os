"""UIF5F qualification for frozen read-only economic performance transport."""

from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.economic_performance_routes as performance_api
from app.api.economic_performance_schemas import EconomicPerformanceRowResponse
from app.attribution.operating_profit_projection_contracts import (
    OPERATING_PROFIT_PROJECTION_SEMANTICS,
    OperatingProfitProjectionRequest,
    OperatingProfitProjectionRow,
)


def _row():
    return OperatingProfitProjectionRow(
        currency="USD",
        net_realized_commission=Decimal("120.50"),
        directly_attributable_cost=Decimal("20.00"),
        contribution_profit=Decimal("100.50"),
        allocated_shared_cost=Decimal("10.00"),
        allocated_contribution_profit=Decimal("90.50"),
        allocated_global_cost=Decimal("5.00"),
        operating_profit=Decimal("85.50"),
        dimensions=(),
    )


def _client(monkeypatch, result=None, error=None):
    calls = []

    class StubService:
        def __init__(self, db):
            calls.append(("init", db))

        def project(self, request):
            calls.append(("project", request))
            if error is not None:
                raise error
            return tuple(result if result is not None else (_row(),))

    monkeypatch.setattr(
        performance_api,
        "AttributionOperatingProfitProjectionService",
        StubService,
    )

    app = FastAPI()
    app.include_router(performance_api.router)
    marker = object()
    app.dependency_overrides[performance_api.get_db] = lambda: marker
    return TestClient(app), calls, marker


def test_route_projects_frozen_operating_profit_exactly_once(monkeypatch):
    client, calls, marker = _client(monkeypatch)

    response = client.get("/economics/performance")

    assert response.status_code == 200
    assert calls[0] == ("init", marker)
    assert len(calls) == 2
    assert calls[1][0] == "project"
    request = calls[1][1]
    assert isinstance(request, OperatingProfitProjectionRequest)
    assert request.dimensions == ()
    assert request.currency is None


def test_route_serializes_native_currency_metrics_without_dimensions(monkeypatch):
    client, _, _ = _client(monkeypatch)

    body = client.get("/economics/performance").json()

    assert body == {
        "rows": [
            {
                "currency": "USD",
                "net_realized_commission": "120.50",
                "directly_attributable_cost": "20.00",
                "contribution_profit": "100.50",
                "allocated_shared_cost": "10.00",
                "allocated_contribution_profit": "90.50",
                "allocated_global_cost": "5.00",
                "operating_profit": "85.50",
                "semantics": OPERATING_PROFIT_PROJECTION_SEMANTICS,
            }
        ]
    }


def test_route_preserves_legitimate_empty_projection(monkeypatch):
    client, calls, _ = _client(monkeypatch, result=())

    response = client.get("/economics/performance")

    assert response.status_code == 200
    assert response.json() == {"rows": []}
    assert [name for name, _ in calls] == ["init", "project"]


def test_route_maps_frozen_authority_rejection_to_conflict(monkeypatch):
    client, calls, _ = _client(
        monkeypatch,
        error=ValueError("M10 allocation authority is inconsistent"),
    )

    response = client.get("/economics/performance")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("economic projection authority conflict:")
    assert len(calls) == 2


def test_response_schema_excludes_internal_dimensions():
    row = EconomicPerformanceRowResponse.model_validate(_row())

    assert row.currency == "USD"
    assert row.operating_profit == Decimal("85.50")
    assert not hasattr(row, "dimensions")


def test_response_schema_preserves_frozen_semantics():
    row = EconomicPerformanceRowResponse.model_validate(_row())

    assert row.semantics == OPERATING_PROFIT_PROJECTION_SEMANTICS
    assert "native currency/no FX" in row.semantics
    assert "not period/accounting-final profit" in row.semantics


def test_router_exposes_get_only():
    route = next(
        route
        for route in performance_api.router.routes
        if getattr(route, "path", None) == "/economics/performance"
    )

    assert route.methods == {"GET"}
