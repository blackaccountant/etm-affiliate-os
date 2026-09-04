"""UIF5B qualification for read-only opportunity discovery-run visibility."""

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.discovery import router
from app.dependencies import get_discovery_query_service
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.services.discovery_query_service import DiscoveryQueryService


def _run(run_id: str = "run-001"):
    now = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    return {
        "id": run_id, "input_type": "keyword", "input_value": "web hosting",
        "input_data": {"market": "global"}, "status": "completed",
        "idempotency_key": None, "candidate_count": 3, "verified_count": 2,
        "selected_count": 1, "last_error": None, "created_at": now,
        "updated_at": now, "completed_at": now,
    }


class StubQueryService:
    def __init__(self):
        self.limits = []

    def list_runs(self, limit: int = 50):
        self.limits.append(limit)
        return [_run()]


def _client(stub):
    app = FastAPI()
    app.include_router(router, prefix="/discovery")
    app.dependency_overrides[get_discovery_query_service] = lambda: stub
    return TestClient(app)


def test_list_runs_defaults_to_fifty_and_serializes_contract():
    stub = StubQueryService()
    response = _client(stub).get("/discovery/runs")
    assert response.status_code == 200
    assert stub.limits == [50]
    assert response.json()[0]["id"] == "run-001"
    assert response.json()[0]["selected_count"] == 1


def test_list_runs_forwards_explicit_limit():
    stub = StubQueryService()
    assert _client(stub).get("/discovery/runs?limit=7").status_code == 200
    assert stub.limits == [7]


def test_list_runs_rejects_zero_limit():
    stub = StubQueryService()
    assert _client(stub).get("/discovery/runs?limit=0").status_code == 422
    assert stub.limits == []


def test_list_runs_rejects_limit_above_one_hundred():
    stub = StubQueryService()
    assert _client(stub).get("/discovery/runs?limit=101").status_code == 422
    assert stub.limits == []


def test_query_service_delegates_to_run_repository():
    class StubRunRepository:
        def __init__(self): self.limits = []
        def list_recent(self, limit=50):
            self.limits.append(limit)
            return ["run-a", "run-b"]
    service = DiscoveryQueryService.__new__(DiscoveryQueryService)
    service.runs = StubRunRepository()
    assert service.list_runs(9) == ["run-a", "run-b"]
    assert service.runs.limits == [9]


def test_repository_recent_listing_applies_order_and_limit():
    calls = []
    class FakeQuery:
        def order_by(self, *expressions): calls.append(("order_by", len(expressions))); return self
        def limit(self, value): calls.append(("limit", value)); return self
        def all(self): calls.append(("all",)); return ["newest", "older"]
    class FakeDb:
        def query(self, model): calls.append(("query", model.__name__)); return FakeQuery()
    repository = DiscoveryRunRepository(FakeDb())
    assert repository.list_recent(limit=2) == ["newest", "older"]
    assert calls == [("query", "DiscoveryRun"), ("order_by", 2), ("limit", 2), ("all",)]
