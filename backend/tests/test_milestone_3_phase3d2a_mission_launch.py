import json

import pytest

from app.discovery.contracts import DiscoveryInputType, DiscoveryRunCreate, DiscoveryRunStatus
from app.mission.manager import MissionManager
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.services.discovery_mission_launch_service import DiscoveryMissionLaunchResult, DiscoveryMissionLaunchService
from app.workflow_engine.workflow_result import WorkflowResult
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


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


def make_service(db_session_factory, workers=None):
    workforce = WorkforceManager()
    selected_workers = workers if workers is not None else [WorkerInfo("Product Hunter", "Research", ["affiliate_research"], status=WorkerStatus.ONLINE)]
    for worker in selected_workers:
        workforce.register(worker)
    manager = MissionManager(workforce=workforce, session_factory=db_session_factory)
    manager.executor.engine = type(
        "StubEngine",
        (),
        {"run": lambda self, workflow_name, payload: WorkflowResult(success=True, workflow=workflow_name, data={"ok": True})},
    )()
    return DiscoveryMissionLaunchService(mission_manager=manager), manager


def test_launch_creates_durable_mission_with_discovery_policy(db_session_factory):
    service, manager = make_service(db_session_factory)
    run = create_run(db_session_factory())

    launch = service.launch(run.id, top_n=2, minimum_score=55, minimum_evidence_confidence=80)

    assert isinstance(launch, DiscoveryMissionLaunchResult)
    assert launch.discovery_run_id == run.id
    assert launch.workflow == "affiliate_discovery_run"
    assert launch.required_capability == "affiliate_research"
    assert launch.idempotency_key == f"affiliate-discovery-run:{run.id}"
    assert launch.mission_status == "COMPLETED"
    assert launch.result_success is True
    assert launch.worker_name is None
    assert json.dumps(launch.to_dict())
    assert launch.result_data == {"ok": True}
    assert manager.get_mission(launch.mission_id) is not None


def test_launch_is_idempotent_for_same_durable_run(db_session_factory):
    service, manager = make_service(db_session_factory)
    run = create_run(db_session_factory())

    first = service.launch(run.id)
    second = service.launch(run.id)

    assert first.mission_id == second.mission_id
    assert first.idempotency_key == second.idempotency_key == f"affiliate-discovery-run:{run.id}"
    assert manager.missions().__len__() == 1
    assert db_session_factory().query(MissionRecord).count() == 1
    assert db_session_factory().query(Execution).count() == 1


def test_existing_mission_short_circuits_even_when_run_is_running_completed_or_failed(db_session_factory):
    service, manager = make_service(db_session_factory)
    run = create_run(db_session_factory())
    original = service.launch(run.id)
    before_calls = manager.executor.engine.calls if hasattr(manager.executor.engine, "calls") else 0

    for status in (DiscoveryRunStatus.RUNNING, DiscoveryRunStatus.COMPLETED, DiscoveryRunStatus.FAILED):
        DiscoveryRunRepository(db_session_factory()).update_status(run.id, status)
        repeated = service.launch(run.id)
        assert repeated.mission_id == original.mission_id
        assert repeated.mission_status == original.mission_status

    assert before_calls == 0


def test_launch_rejects_missing_run(db_session_factory):
    service, _ = make_service(db_session_factory)

    with pytest.raises(ValueError, match="discovery run does not exist"):
        service.launch("missing-run")


def test_launch_rejects_running_run_without_duplicate_mission(db_session_factory):
    service, _ = make_service(db_session_factory)
    run = create_run(db_session_factory(), status=DiscoveryRunStatus.RUNNING)

    with pytest.raises(RuntimeError, match="already"):
        service.launch(run.id)


def test_invalid_policy_rejected_without_run_change(db_session_factory):
    service, _ = make_service(db_session_factory)
    run = create_run(db_session_factory())

    with pytest.raises(ValueError, match="top_n"):
        service.launch(run.id, top_n=0)

    refreshed = DiscoveryRunRepository(db_session_factory()).get_by_id(run.id)
    assert refreshed.status == DiscoveryRunStatus.CREATED.value
    assert db_session_factory().query(MissionRecord).count() == 0
    assert db_session_factory().query(Execution).count() == 0


def test_waiting_for_worker_returns_waiting_result_without_execution(db_session_factory):
    service, _ = make_service(db_session_factory, workers=[])
    run = create_run(db_session_factory())

    first = service.launch(run.id)
    second = service.launch(run.id)

    assert first.mission_status == "WAITING_FOR_WORKER"
    assert first.worker_name is None
    assert first.result_success is None
    assert second.mission_id == first.mission_id
    assert db_session_factory().query(MissionRecord).count() == 1
    assert db_session_factory().query(Execution).count() == 0
