"""UIF5E qualification for read-only immutable attribution lineage visibility."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.attribution_lineage_routes as attribution_api
from app.api.attribution_lineage_schemas import (
    AttributionFactVisibilityResponse,
    AttributionPayoutSettlementVisibilityResponse,
)
from app.repositories.attribution_lineage_visibility_repository import (
    AttributionLineageVisibilityRepository,
)
from app.services.attribution_lineage_visibility_service import (
    AttributionLineageVisibilityService,
)


EMPTY_SNAPSHOT = {
    "publications": [],
    "contexts": [],
    "clicks": [],
    "facts": [],
    "earning_links": [],
    "settlement_links": [],
}


class StubService:
    def __init__(self, calls):
        self.calls = calls

    def snapshot(self, limit=50):
        self.calls.append(limit)
        return dict(EMPTY_SNAPSHOT)


def _client(monkeypatch):
    calls = []
    monkeypatch.setattr(
        attribution_api,
        "AttributionLineageVisibilityService",
        lambda repository: StubService(calls),
    )
    app = FastAPI()
    app.include_router(attribution_api.router)
    app.dependency_overrides[attribution_api.get_db] = lambda: object()
    return TestClient(app), calls


def test_lineage_defaults_to_fifty_and_returns_complete_snapshot(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/attribution/lineage")
    assert response.status_code == 200
    assert response.json() == EMPTY_SNAPSHOT
    assert calls == [50]


def test_lineage_forwards_explicit_limit(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/attribution/lineage?limit=7")
    assert response.status_code == 200
    assert calls == [7]


@pytest.mark.parametrize("limit", [0, 101])
def test_lineage_rejects_out_of_bounds_limit_before_service(monkeypatch, limit):
    client, calls = _client(monkeypatch)
    response = client.get(f"/attribution/lineage?limit={limit}")
    assert response.status_code == 422
    assert calls == []


def test_service_reads_each_lineage_collection_exactly_once():
    calls = []

    class StubRepository:
        def __getattr__(self, name):
            if not name.startswith("list_"):
                raise AttributeError(name)

            def read(limit):
                calls.append((name, limit))
                return [name]

            return read

    snapshot = AttributionLineageVisibilityService(StubRepository()).snapshot(9)
    assert snapshot == {
        "publications": ["list_publications"],
        "contexts": ["list_contexts"],
        "clicks": ["list_clicks"],
        "facts": ["list_facts"],
        "earning_links": ["list_earning_links"],
        "settlement_links": ["list_settlement_links"],
    }
    assert calls == [
        ("list_publications", 9),
        ("list_contexts", 9),
        ("list_clicks", 9),
        ("list_facts", 9),
        ("list_earning_links", 9),
        ("list_settlement_links", 9),
    ]


def test_fact_schema_preserves_only_explicit_durable_references():
    now = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)
    row = AttributionFactVisibilityResponse.model_validate({
        "id": "fact-1",
        "fact_kind": "CONVERSION_REPORTED",
        "source_namespace": "impact",
        "attribution_publication_id": None,
        "attribution_context_id": "context-1",
        "attribution_click_id": None,
        "affiliate_link_id": None,
        "affiliate_conversion_id": 44,
        "supersedes_fact_id": None,
        "occurred_at": now,
        "recorded_at": now,
    })
    assert row.attribution_context_id == "context-1"
    assert row.affiliate_conversion_id == 44
    assert not hasattr(row, "customer_reference")
    assert not hasattr(row, "source_event_key_digest")
    assert not hasattr(row, "source_fingerprint")


def test_settlement_schema_exposes_reference_lineage_not_payout_mutation_state():
    now = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)
    row = AttributionPayoutSettlementVisibilityResponse.model_validate({
        "id": "settlement-1",
        "attribution_earning_link_id": "earning-link-1",
        "affiliate_earning_id": 12,
        "affiliate_payout_id": 7,
        "affiliate_payout_attempt_id": 3,
        "source_namespace": "payout-observer",
        "observed_at": now,
        "recorded_at": now,
    })
    assert row.affiliate_payout_id == 7
    assert row.affiliate_payout_attempt_id == 3
    assert not hasattr(row, "linkage_fingerprint")
    assert not hasattr(row, "status")
    assert not hasattr(row, "paid_at")


@pytest.mark.parametrize(
    ("method_name", "model_name"),
    [
        ("list_publications", "AttributionPublication"),
        ("list_contexts", "AttributionContext"),
        ("list_clicks", "AttributionClick"),
        ("list_facts", "AttributionFact"),
        ("list_earning_links", "AttributionEarningLink"),
        ("list_settlement_links", "AttributionPayoutSettlementLink"),
    ],
)
def test_visibility_repository_queries_are_read_only_newest_first(method_name, model_name):
    calls = []

    class FakeQuery:
        def order_by(self, *expressions):
            calls.append(("order_by", len(expressions)))
            return self

        def limit(self, value):
            calls.append(("limit", value))
            return self

        def all(self):
            calls.append(("all",))
            return ["newest", "older"]

    class FakeDb:
        def query(self, model):
            calls.append(("query", model.__name__))
            return FakeQuery()

    repository = AttributionLineageVisibilityRepository(FakeDb())
    result = getattr(repository, method_name)(6)

    assert result == ["newest", "older"]
    assert calls == [
        ("query", model_name),
        ("order_by", 2),
        ("limit", 6),
        ("all",),
    ]
