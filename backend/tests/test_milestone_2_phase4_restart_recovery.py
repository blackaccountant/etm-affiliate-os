"""SQLite-only restart recovery acceptance tests for Phase 4B."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.executor.executor import TaskExecutor
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.system import runtime as runtime_module
from app.task_queue.task import Task
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


class Engine:
    def __init__(self, result=None, error=None, inspect=None):
        self.result = result
        self.error = error
        self.inspect = inspect
        self.calls = 0

    def run(self, workflow_name, payload):
        self.calls += 1
        if self.inspect:
            self.inspect()
        if self.error:
            raise self.error
        return self.result


def seed_retry(db_session_factory, worker_name="Product Hunter", retry_count=1):
    session = db_session_factory()
    try:
        missions = MissionRepository(session)
        workers = WorkerRepository(session)
        executions = ExecutionRepository(session)
        mission = missions.create(
            mission_id="mission-retry", name="Recovered Mission", objective="Recover",
            workflow_name="test_workflow", input_data={"input": True}, current_worker_name=worker_name,
        )
        missions.update_status(mission.id, "RETRY_WAIT", current_worker_name=worker_name)
        workers.create(worker_name, "Test", capabilities=["recovery"], status=WorkerStatus.ONLINE)
        assert workers.claim(worker_name, mission.id) is True
        execution = executions.create(
            "test_workflow", "QUEUED", mission.id, mission.name, worker_name,
            input_data=json.dumps({"input": True}), retry_count=retry_count, max_retries=3,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            failure_type="NETWORK", error="previous network timeout",
        )
        return mission.id, execution.id
    finally:
        session.close()


def durable_state(db_session_factory, mission_id, execution_id, worker_name="Product Hunter"):
    session = db_session_factory()
    try:
        return (
            session.get(MissionRecord, mission_id),
            session.get(Execution, execution_id),
            session.get(Worker, worker_name),
        )
    finally:
        session.close()


def coordinator_for(db_session_factory, mission_id, execution_id, engine, workforce=None):
    session = db_session_factory()
    service = ExecutionService(ExecutionRepository(session))
    workforce = workforce or WorkforceManager()
    executor = TaskExecutor(execution_service=service)
    executor.workforce = None
    executor.engine = engine
    coordinator = RetryLifecycleCoordinator(
        session, service, MissionRepository(session), WorkerRepository(session), workforce, executor,
    )
    execution = service.claim_retry(service.get_by_id(execution_id))
    task = Task("test_workflow", {
        "input": True, "mission_id": mission_id, "execution_id": execution_id,
        "worker_name": execution.worker_name, "retry_count": execution.retry_count,
        "max_retries": execution.max_retries, "failure_type": execution.failure_type,
    })
    task.retry_count = execution.retry_count
    task.max_retries = execution.max_retries
    return session, coordinator, task, workforce


def test_scanner_restores_original_worker_name(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)
    session = db_session_factory()
    try:
        service = ExecutionService(ExecutionRepository(session))
        tasks = RetryScanner(service, Scheduler()).scan_once()
        assert tasks[0].payload["mission_id"] == mission_id
        assert tasks[0].payload["execution_id"] == execution_id
        assert tasks[0].payload["worker_name"] == "Product Hunter"
    finally:
        session.close()


def test_recovered_success_uses_original_busy_worker_and_completes(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)
    observed = {}
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Product Hunter", "Stale", status=WorkerStatus.ONLINE))

    def inspect():
        mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
        runtime_worker = workforce.get_worker("Product Hunter")
        observed.update(
            mission=mission.status, execution=execution.status, worker=worker.status,
            task_worker=task.worker.name, runtime_worker=runtime_worker.status,
        )

    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id,
        Engine({"success": True, "data": {"recovered": True}, "errors": []}, inspect=inspect), workforce,
    )
    try:
        coordinator.execute(task)
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert observed == {
        "mission": "RUNNING", "execution": "RETRYING", "worker": "BUSY",
        "task_worker": "Product Hunter", "runtime_worker": WorkerStatus.BUSY,
    }
    assert mission.status == "COMPLETED" and mission.current_worker_name is None
    assert execution.status == "COMPLETED"
    assert worker.status == "ONLINE" and worker.current_mission_id is None
    assert worker.missions_completed == 1 and workforce.get_worker("Product Hunter").status is WorkerStatus.ONLINE


def test_retry_again_preserves_mission_and_worker_ownership(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)
    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id,
        Engine({"success": False, "errors": ["network timeout"]}),
    )
    try:
        coordinator.execute(task)
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert execution.status == "QUEUED" and mission.status == "RETRY_WAIT"
    assert mission.current_worker_name == "Product Hunter"
    assert worker.status == "BUSY" and worker.current_mission_id == mission_id
    assert worker.missions_completed == 0 and workforce.get_worker("Product Hunter").status is WorkerStatus.BUSY


def test_exhaustion_and_terminal_exception_release_once(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory, retry_count=2)
    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id, Engine(error=RuntimeError("terminal failure")),
    )
    try:
        with pytest.raises(RuntimeError, match="terminal failure"):
            coordinator.execute(task)
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert execution.status == "FAILED" and mission.status == "FAILED"
    assert mission.current_worker_name is None and worker.status == "ONLINE"
    assert worker.missions_completed == 1 and worker.missions_failed == 1
    assert workforce.get_worker("Product Hunter").status is WorkerStatus.ONLINE


def test_retryable_python_exception_uses_persisted_metadata(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)
    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id, Engine(error=RuntimeError("network timeout")),
    )
    try:
        assert coordinator.execute(task) is None
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert execution.status == "QUEUED" and execution.error == "network timeout"
    assert mission.status == "RETRY_WAIT" and worker.status == "BUSY"
    assert workforce.get_worker("Product Hunter").status is WorkerStatus.BUSY


@pytest.mark.parametrize("mutate", ["missing_mission", "missing_worker", "wrong_mission_worker", "wrong_worker_mission", "online_worker"])
def test_ownership_mismatch_fails_only_execution(db_session_factory, mutate):
    mission_id, execution_id = seed_retry(db_session_factory)
    session = db_session_factory()
    try:
        mission = session.get(MissionRecord, mission_id)
        worker = session.get(Worker, "Product Hunter")
        if mutate == "missing_mission":
            session.delete(mission)
        elif mutate == "missing_worker":
            session.delete(worker)
        elif mutate == "wrong_mission_worker":
            mission.current_worker_name = "Other"
        elif mutate == "wrong_worker_mission":
            worker.current_mission_id = "other-mission"
        else:
            worker.status = "ONLINE"
        session.commit()
    finally:
        session.close()

    engine = Engine({"success": True, "errors": []})
    session, coordinator, task, _ = coordinator_for(db_session_factory, mission_id, execution_id, engine)
    try:
        assert coordinator.execute(task) is None
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert engine.calls == 0 and execution.status == "FAILED"
    assert execution.failure_type == "OWNERSHIP_RECOVERY"
    if mission is not None:
        assert mission.status == "RETRY_WAIT"
    if worker is not None:
        assert worker.status != "ONLINE" or mutate == "online_worker"


def test_scheduling_failure_restores_execution_without_changing_ownership(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)
    session = db_session_factory()
    try:
        service = ExecutionService(ExecutionRepository(session))

        class BrokenScheduler:
            def schedule(self, *args, **kwargs):
                raise RuntimeError("scheduler unavailable")

        assert RetryScanner(service, BrokenScheduler()).scan_once() == []
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert execution.status == "QUEUED" and mission.status == "RETRY_WAIT" and worker.status == "BUSY"


def test_unexpected_retrying_status_is_requeued(db_session_factory):
    mission_id, execution_id = seed_retry(db_session_factory)

    class NoPersistenceExecutor:
        def execute(self, task):
            return {"success": True}

    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id, Engine({"success": True}),
    )
    coordinator.executor = NoPersistenceExecutor()
    try:
        assert coordinator.execute(task) == {"success": True}
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert execution.status == "QUEUED" and mission.status == "RETRY_WAIT" and worker.status == "BUSY"


def test_durable_release_fence_rolls_back_without_releasing_in_memory_worker(db_session_factory, monkeypatch):
    mission_id, execution_id = seed_retry(db_session_factory)
    session, coordinator, task, workforce = coordinator_for(
        db_session_factory, mission_id, execution_id, Engine({"success": True, "errors": []}),
    )
    monkeypatch.setattr(WorkerRepository, "release", lambda *args, **kwargs: False)
    try:
        assert coordinator.execute(task) is None
    finally:
        session.close()
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert (mission.status, execution.status, worker.status) == ("RUNNING", "RETRYING", "BUSY")
    assert workforce.get_worker("Product Hunter").status is WorkerStatus.BUSY


def test_runtime_adapter_reconstructs_and_closes_injected_session(db_session_factory, monkeypatch):
    mission_id, execution_id = seed_retry(db_session_factory)
    calls = []

    class TrackedSession:
        def __init__(self):
            self.session = db_session_factory()
            self.closed = False

        def close(self):
            self.closed = True
            self.session.close()

        def __getattr__(self, name):
            return getattr(self.session, name)

    def factory():
        calls.append(TrackedSession())
        return calls[-1]

    observed = {}

    def run(engine, workflow_name, payload):
        mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
        observed.update(mission=mission.status, execution=execution.status, worker=worker.status)
        return {"success": True, "errors": []}

    monkeypatch.setattr("app.workflow_engine.workflow_engine.WorkflowEngine.run", run)
    runtime = runtime_module.RuntimeAdapter(session_factory=factory)
    assert calls == []
    assert runtime._process_retry_cycle() == [{"success": True, "errors": []}]
    mission, execution, worker = durable_state(db_session_factory, mission_id, execution_id)
    assert observed == {"mission": "RUNNING", "execution": "RETRYING", "worker": "BUSY"}
    assert mission.status == "COMPLETED" and execution.status == "COMPLETED" and worker.status == "ONLINE"
    assert len(calls) == 1 and calls[0].closed is True
