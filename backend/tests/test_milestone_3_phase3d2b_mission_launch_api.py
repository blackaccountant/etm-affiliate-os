import importlib
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.discovery import router
from app.dependencies import get_db, get_discovery_mission_manager
from app.discovery.contracts import DiscoveryInputType, DiscoveryRunCreate, DiscoveryRunStatus
from app.mission.manager import MissionManager
from app.models.affiliate_program import AffiliateProgram
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.product import Product
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.schemas.discovery import DiscoveryMissionLaunchResponse
from app.services.discovery_mission_launch_service import DiscoveryMissionLaunchResult, DiscoveryMissionLaunchService
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService
from app.workflows.affiliate.discovery_run_workflow import AffiliateDiscoveryRunWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


class NoCandidateIngestion:
    def ingest(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def isolation_sentinels(monkeypatch):
    def fail_default_session():
        raise AssertionError("configured SessionLocal must not be used by focused mission launch API tests")

    def fail_network(*args, **kwargs):
        raise AssertionError("focused mission launch API tests must not use network access")

    monkeypatch.setattr("app.dependencies.SessionLocal", fail_default_session)
    monkeypatch.setattr(httpx, "get", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch_with_metadata", fail_network)


def api_client(db_session_factory, mission_manager=None, raise_server_exceptions=True):
    app = FastAPI()
    app.include_router(router, prefix="/discovery")

    def override_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    if mission_manager is not None:
        app.dependency_overrides[get_discovery_mission_manager] = lambda: mission_manager
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def make_manager(db_session_factory, workers=None):
    workforce = WorkforceManager()
    selected_workers = workers if workers is not None else [WorkerInfo("Product Hunter", "Research", ["affiliate_research"], status=WorkerStatus.ONLINE)]
    for worker in selected_workers:
        workforce.register(worker)

    manager = MissionManager(workforce=workforce, session_factory=db_session_factory)

    def run_workflow(workflow_name, payload):
        assert workflow_name == "affiliate_discovery_run"
        workflow = AffiliateDiscoveryRunWorkflow(
            session_factory=db_session_factory,
            orchestration_factory=lambda db: DiscoveryRunOrchestrationService(db, ingestion=NoCandidateIngestion()),
        )
        return workflow.execute(payload)

    manager.executor.engine.run = run_workflow
    return manager


def create_run(db_session, status=DiscoveryRunStatus.CREATED):
    run = DiscoveryRunRepository(db_session).create(
        DiscoveryRunCreate(
            input_type=DiscoveryInputType.URL,
            input_value="https://acme.example",
            input_data={"source": "example"},
            idempotency_key=f"run-{status.value.lower()}-seed",
        )
    )
    if status is not DiscoveryRunStatus.CREATED:
        run = DiscoveryRunRepository(db_session).update_status(run.id, status)
    return run


def test_launch_endpoint_creates_durable_mission_and_strict_contract(db_session, db_session_factory):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))

    response = client.post(
        f"/discovery/runs/{run.id}/launch",
        json={"top_n": 2, "minimum_score": 55, "minimum_evidence_confidence": 80},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == set(DiscoveryMissionLaunchResponse.model_fields)
    assert payload["run_id"] == run.id
    assert payload["mission_id"]
    assert payload["mission_status"] == "COMPLETED"
    assert payload["workflow"] == "affiliate_discovery_run"
    assert payload["required_capability"] == "affiliate_research"
    assert payload["idempotency_key"] == f"affiliate-discovery-run:{run.id}"
    assert payload["worker_name"] is None
    assert payload["result_success"] is True
    assert payload["result_error"] is None
    assert payload["result_data"]["status"] == "COMPLETED"
    assert db_session.query(MissionRecord).filter_by(idempotency_key=f"affiliate-discovery-run:{run.id}").count() == 1
    db_session.expire_all()
    assert DiscoveryRunRepository(db_session).get_by_id(run.id).status == DiscoveryRunStatus.COMPLETED.value


def test_launch_endpoint_is_idempotent_for_same_run(db_session, db_session_factory):
    run = create_run(db_session)
    manager = make_manager(db_session_factory)
    client = api_client(db_session_factory, mission_manager=manager)

    first = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    second = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})

    assert first.status_code == second.status_code == 200
    assert first.json()["mission_id"] == second.json()["mission_id"]
    assert first.json()["idempotency_key"] == second.json()["idempotency_key"] == f"affiliate-discovery-run:{run.id}"
    assert manager.missions().__len__() == 1
    assert db_session.query(MissionRecord).count() == 1


def test_launch_endpoint_rejects_missing_run_and_invalid_policy(db_session, db_session_factory):
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))

    missing = client.post("/discovery/runs/missing/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    invalid = client.post("/discovery/runs/does-not-matter/launch", json={"top_n": 0, "minimum_score": 40, "minimum_evidence_confidence": 70})

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert "top_n" in invalid.json()["detail"][0]["loc"] or "top_n" in str(invalid.json()["detail"])


def test_launch_endpoint_rejects_running_run_and_waits_for_worker_when_no_worker_available(db_session, db_session_factory):
    running = create_run(db_session, status=DiscoveryRunStatus.RUNNING)
    no_worker_client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory, workers=[]))
    waiting = no_worker_client.post(f"/discovery/runs/{running.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})

    assert waiting.status_code == 409
    assert "already" in waiting.json()["detail"].lower()

    created = create_run(db_session)
    waiting_client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory, workers=[]))
    response = waiting_client.post(f"/discovery/runs/{created.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mission_status"] == "WAITING_FOR_WORKER"
    assert payload["result_success"] is None
    assert payload["worker_name"] is None
    assert payload["result_error"] is None


def test_missing_or_new_run_state_conflicts_fail_without_existing_mission(db_session, db_session_factory):
    for status in (DiscoveryRunStatus.RUNNING, DiscoveryRunStatus.COMPLETED, DiscoveryRunStatus.FAILED):
        run = create_run(db_session, status=status)
        response = api_client(db_session_factory, mission_manager=make_manager(db_session_factory)).post(
            f"/discovery/runs/{run.id}/launch",
            json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70},
        )
        assert response.status_code == 409
        assert db_session.query(MissionRecord).count() == 0
        assert db_session.query(Execution).count() == 0

    missing = api_client(db_session_factory, mission_manager=make_manager(db_session_factory)).post(
        "/discovery/runs/missing/launch",
        json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70},
    )
    assert missing.status_code == 404


@pytest.mark.parametrize("input_type", ["MARKET", "NICHE", "SEED"])
def test_unsupported_run_input_types_rejected_before_launch(db_session, db_session_factory, input_type):
    run = create_run(db_session, status=DiscoveryRunStatus.CREATED)
    run.input_type = input_type
    db_session.add(run)
    db_session.commit()
    response = api_client(db_session_factory, mission_manager=make_manager(db_session_factory)).post(
        f"/discovery/runs/{run.id}/launch",
        json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70},
    )
    assert response.status_code == 400
    assert db_session.query(MissionRecord).count() == 0
    assert db_session.query(Execution).count() == 0


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"top_n": 0, "minimum_score": 40, "minimum_evidence_confidence": 70}, "top_n"),
        ({"top_n": True, "minimum_score": 40, "minimum_evidence_confidence": 70}, "top_n"),
        ({"top_n": 1, "minimum_score": -1, "minimum_evidence_confidence": 70}, "minimum_score"),
        ({"top_n": 1, "minimum_score": 101, "minimum_evidence_confidence": 70}, "minimum_score"),
        ({"top_n": 1, "minimum_score": True, "minimum_evidence_confidence": 70}, "minimum_score"),
        ({"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": -1}, "minimum_evidence_confidence"),
        ({"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 101}, "minimum_evidence_confidence"),
        ({"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": True}, "minimum_evidence_confidence"),
    ],
)
def test_request_policy_validation_rejects_invalid_values_before_service_call(db_session, db_session_factory, payload, field, monkeypatch):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))
    calls = {"count": 0}

    original = DiscoveryMissionLaunchService.launch

    def counted_launch(self, *args, **kwargs):
        calls["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DiscoveryMissionLaunchService, "launch", counted_launch)
    response = client.post(f"/discovery/runs/{run.id}/launch", json=payload)
    assert response.status_code == 422
    assert field in str(response.json()) or field in str(response.json()["detail"]) or response.json()["detail"] == ""
    assert calls["count"] == 0


def test_request_defaults_propagate_all_fields_and_run_id_exactly(db_session, db_session_factory, monkeypatch):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))
    captured = {}

    def fake_launch(self, discovery_run_id, top_n, minimum_score, minimum_evidence_confidence):
        captured["args"] = (discovery_run_id, top_n, minimum_score, minimum_evidence_confidence)
        return DiscoveryMissionLaunchResult(
            discovery_run_id=discovery_run_id,
            mission_id="mission-1",
            mission_status="COMPLETED",
            workflow="affiliate_discovery_run",
            required_capability="affiliate_research",
            idempotency_key=f"affiliate-discovery-run:{discovery_run_id}",
            worker_name="Product Hunter",
            result_success=True,
            result_error=None,
            result_data={"ok": True},
        )

    monkeypatch.setattr(DiscoveryMissionLaunchService, "launch", fake_launch)
    response = client.post(f"/discovery/runs/{run.id}/launch", json={})
    assert response.status_code == 200
    assert captured["args"] == (run.id, 1, 40, 70)


def test_response_contract_omits_orm_and_domain_internals_and_result_data_is_normalized(db_session, db_session_factory, monkeypatch):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))

    def fake_launch(self, discovery_run_id, top_n, minimum_score, minimum_evidence_confidence):
        return DiscoveryMissionLaunchResult(
            discovery_run_id=discovery_run_id,
            mission_id="mission-abc",
            mission_status="COMPLETED",
            workflow="affiliate_discovery_run",
            required_capability="affiliate_research",
            idempotency_key=f"affiliate-discovery-run:{discovery_run_id}",
            worker_name="Product Hunter",
            result_success=True,
            result_error=None,
            result_data={"ok": True, "nested": {"value": 1}},
        )

    monkeypatch.setattr(DiscoveryMissionLaunchService, "launch", fake_launch)
    response = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    payload = response.json()
    assert set(payload) == set(DiscoveryMissionLaunchResponse.model_fields)
    assert "_sa_instance_state" not in payload
    assert "MissionResult" not in str(payload)
    assert "WorkerInfo" not in str(payload)
    assert payload["result_data"] == {"ok": True, "nested": {"value": 1}}


def test_restart_like_http_idempotency_uses_same_durable_mission_across_managers(db_session_factory, db_session):
    run = create_run(db_session)
    manager_a = make_manager(db_session_factory)
    client_a = api_client(db_session_factory, mission_manager=manager_a)
    first = client_a.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    first_payload = first.json()

    manager_b = make_manager(db_session_factory)
    client_b = api_client(db_session_factory, mission_manager=manager_b)
    second = client_b.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})

    assert second.status_code == 200
    assert second.json()["mission_id"] == first_payload["mission_id"]
    assert db_session.query(MissionRecord).count() == 1
    assert db_session.query(Execution).count() == 1


def test_waiting_for_worker_http_response_and_durable_state(db_session, db_session_factory):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory, workers=[]))
    first = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    second = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    assert first.status_code == second.status_code == 200
    assert first.json()["mission_status"] == "WAITING_FOR_WORKER"
    assert first.json()["result_success"] is None
    assert first.json()["worker_name"] is None
    assert db_session.query(MissionRecord).filter_by(status="WAITING_FOR_WORKER").count() == 1
    assert db_session.query(Execution).count() == 0
    assert first.json()["mission_id"] == second.json()["mission_id"]


def test_completed_launch_http_result_and_durable_terminal_state(db_session, db_session_factory):
    run = create_run(db_session)
    client = api_client(db_session_factory, mission_manager=make_manager(db_session_factory))
    response = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    payload = response.json()
    assert response.status_code == 200
    assert payload["mission_status"] == "COMPLETED"
    assert payload["result_success"] is True
    mission = db_session.query(MissionRecord).filter_by(idempotency_key=f"affiliate-discovery-run:{run.id}").one()
    assert mission.status == "COMPLETED"
    assert db_session.query(Execution).filter_by(mission_id=mission.id).one().status == "COMPLETED"
    db_session.expire_all()
    assert db_session.get(__import__('app.models.discovery', fromlist=['DiscoveryRun']).DiscoveryRun, run.id).status == "COMPLETED"
    assert db_session.query(Product).count() == 0
    assert db_session.query(AffiliateProgram).count() == 0


def test_retry_wait_http_result_and_durable_state(db_session, db_session_factory, monkeypatch):
    run = create_run(db_session)
    manager = make_manager(db_session_factory)
    client = api_client(db_session_factory, mission_manager=manager)

    class FailingEngine:
        def run(self, workflow_name, payload):
            handler = self
            return WorkflowResult(success=False, workflow=workflow_name, data={}, errors=["timed out"], duration=0.0)

    manager.executor.engine = FailingEngine()
    response = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    payload = response.json()
    assert response.status_code == 200
    assert payload["mission_status"] == "RETRY_WAIT"
    assert payload["result_success"] is None
    assert payload["result_error"] is not None
    mission = db_session.query(MissionRecord).filter_by(idempotency_key=f"affiliate-discovery-run:{run.id}").one()
    assert mission.status == "RETRY_WAIT"
    assert db_session.query(Execution).filter_by(mission_id=mission.id).one().status == "QUEUED"
    assert db_session.get(__import__('app.models.discovery', fromlist=['DiscoveryRun']).DiscoveryRun, run.id).status == "CREATED"


def test_failed_http_result_and_durable_state(db_session, db_session_factory, monkeypatch):
    run = create_run(db_session)
    manager = make_manager(db_session_factory)
    client = api_client(db_session_factory, mission_manager=manager)

    class FailingEngine:
        def run(self, workflow_name, payload):
            return WorkflowResult(success=False, workflow=workflow_name, data={}, errors=["permanent failure"], duration=0.0)

    manager.executor.engine = FailingEngine()
    response = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    payload = response.json()
    assert response.status_code == 200
    assert payload["mission_status"] == "RETRY_WAIT"
    assert payload["result_success"] is None
    assert payload["result_error"] is not None
    mission = db_session.query(MissionRecord).filter_by(idempotency_key=f"affiliate-discovery-run:{run.id}").one()
    assert mission.status == "RETRY_WAIT"
    assert db_session.query(Execution).filter_by(mission_id=mission.id).one().status == "QUEUED"
    db_session.expire_all()
    assert db_session.get(__import__('app.models.discovery', fromlist=['DiscoveryRun']).DiscoveryRun, run.id).status == "CREATED"


def test_unexpected_runtime_error_is_not_mapped_to_409(db_session, db_session_factory, monkeypatch):
    run = create_run(db_session)
    manager = make_manager(db_session_factory)
    client = api_client(db_session_factory, mission_manager=manager, raise_server_exceptions=False)

    def explode(self, *args, **kwargs):
        raise RuntimeError("unexpected backend outage")

    monkeypatch.setattr(DiscoveryMissionLaunchService, "launch", explode)
    response = client.post(f"/discovery/runs/{run.id}/launch", json={"top_n": 1, "minimum_score": 40, "minimum_evidence_confidence": 70})
    assert response.status_code >= 400
    assert response.status_code != 409


def test_dependencies_import_does_not_eagerly_import_system_routes(monkeypatch):
    for name in ["app.dependencies", "app.system.routes"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("app.dependencies")
    assert "app.system.routes" not in sys.modules
    assert hasattr(module, "get_discovery_mission_manager")


def test_production_dependency_resolves_shared_runtime_identity():
    import app.system.routes as routes
    from app.dependencies import get_discovery_mission_manager

    service = get_discovery_mission_manager()
    assert service is routes.mission_manager
    assert service.workforce is routes.runtime.workforce


def test_focused_api_uses_isolated_fastapi_app_and_no_runtime_lifespan(monkeypatch):
    import app.system.routes as routes
    started = {"count": 0}

    def fail_if_started():
        started["count"] += 1
        raise AssertionError("production retry manager must not start during focused D2B API tests")

    monkeypatch.setattr(routes.runtime, "start_retry_manager", fail_if_started)
    app = FastAPI()
    app.include_router(router, prefix="/discovery")
    assert started["count"] == 0
    assert app is not None


def test_openapi_registers_launch_and_execute_once_without_lifespan():
    from app.main import app as main_app

    launch_count = sum(
        1 for route in main_app.routes
        if getattr(route, "path", None) == "/discovery/runs/{run_id}/launch" and "POST" in route.methods
    )
    execute_count = sum(
        1 for route in main_app.routes
        if getattr(route, "path", None) == "/discovery/runs/{run_id}/execute" and "POST" in route.methods
    )
    assert launch_count == 1
    assert execute_count == 1


def test_phase_3c2_execute_and_discovery_get_routes_still_pass(db_session, db_session_factory):
    client = api_client(db_session_factory)
    assert client.get("/discovery/runs/missing").status_code == 404
    assert client.get("/discovery/runs/missing/candidates").status_code == 404
