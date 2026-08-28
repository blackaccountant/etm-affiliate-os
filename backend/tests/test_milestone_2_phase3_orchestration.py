"""SQLite-only acceptance coverage for durable mission orchestration."""

import json
from types import SimpleNamespace

import pytest

from app.memory.memory_bus import MemoryBus
from app.mission.manager import MissionManager
from app.mission.status import MissionStatus
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
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


def successful_result():
    return {"success": True, "workflow": "test_workflow", "data": {"test": True}, "errors": []}


def failed_result(error):
    return {"success": False, "workflow": "test_workflow", "data": {"test": True}, "errors": [error]}


def make_manager(db_session_factory, workers=(), runtime=None):
    workforce = WorkforceManager()
    for worker in workers:
        workforce.register(worker)
    manager = MissionManager(workforce=workforce, session_factory=db_session_factory)
    if runtime is not None:
        # Keep TaskExecutor's own optional runtime hooks out of these focused tests.
        manager.runtime = runtime
    return manager, workforce


def online_worker(name="Worker", capabilities=None):
    return WorkerInfo(name, "Test", capabilities=capabilities or [], status=WorkerStatus.ONLINE)


def records(session_factory, mission_id):
    session = session_factory()
    try:
        return (
            session.get(MissionRecord, mission_id),
            session.query(Execution).filter(Execution.mission_id == mission_id).one_or_none(),
            session.query(Worker).one_or_none(),
        )
    finally:
        session.close()


def test_success_persists_lifecycle_before_and_after_engine(db_session_factory):
    observed = {}

    def inspect():
        session = db_session_factory()
        try:
            mission = session.query(MissionRecord).one()
            execution = session.query(Execution).one()
            worker = session.query(Worker).one()
            observed.update(
                mission_status=mission.status,
                execution_status=execution.status,
                worker_status=worker.status,
                worker_mission=worker.current_mission_id,
            )
        finally:
            session.close()

    runtime = SimpleNamespace(memory=MemoryBus())
    manager, workforce = make_manager(db_session_factory, [online_worker()], runtime)
    engine = Engine(successful_result(), inspect=inspect)
    manager.executor.engine = engine

    launch = manager.launch("Mission", "Objective", "test_workflow", {"value": 1})
    mission, execution, worker = records(db_session_factory, launch["mission"].id)

    assert observed == {
        "mission_status": "RUNNING",
        "execution_status": "RUNNING",
        "worker_status": "BUSY",
        "worker_mission": launch["mission"].id,
    }
    assert launch["result"].success is True
    assert mission.status == "COMPLETED" and mission.completed_at is not None
    assert mission.current_worker_name is None and mission.last_error is None
    assert json.loads(mission.result_data)["data"] == {"test": True}
    assert execution.status == "COMPLETED" and execution.completed_at is not None
    assert worker.status == "ONLINE" and worker.current_mission_id is None
    assert worker.missions_completed == 1 and worker.missions_failed == 0
    assert workforce.get_worker("Worker").status is WorkerStatus.ONLINE
    assert manager.scheduler.queue.is_empty()
    assert runtime.memory.get("latest_mission_result")["status"] == "COMPLETED"


def test_transition_failure_preserves_domain_and_prevents_engine(db_session_factory, monkeypatch):
    runtime = SimpleNamespace(memory=MemoryBus())
    manager, _ = make_manager(db_session_factory, [online_worker()], runtime)
    engine = Engine(successful_result())
    manager.executor.engine = engine

    def fail_update(*args, **kwargs):
        raise RuntimeError("durable transition failed")

    monkeypatch.setattr(MissionRepository, "update_status", fail_update)

    with pytest.raises(RuntimeError, match="durable transition failed"):
        manager.launch("Mission", "Objective", "test_workflow")

    mission = manager.missions()[0]
    assert mission.status is MissionStatus.CREATED
    assert engine.calls == 0
    assert runtime.memory.get("latest_mission_result") is None


def test_transition_missing_record_preserves_domain_state(db_session_factory):
    manager, _ = make_manager(db_session_factory)
    mission = manager.create_mission("Mission", "Objective", "test_workflow")

    class MissingRepository:
        def update_status(self, *args, **kwargs):
            return None

    with pytest.raises(RuntimeError, match="Durable mission record disappeared"):
        manager._transition(mission, MissingRepository(), MissionStatus.WAITING_FOR_WORKER)

    assert mission.status is MissionStatus.CREATED


def test_release_failure_keeps_runtime_worker_busy_and_writes_no_result(db_session_factory, monkeypatch):
    runtime = SimpleNamespace(memory=MemoryBus())
    manager, workforce = make_manager(db_session_factory, [online_worker()], runtime)
    manager.executor.engine = Engine(successful_result())
    monkeypatch.setattr(WorkerRepository, "release", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="Durable worker release failed"):
        manager.launch("Mission", "Objective", "test_workflow")

    assert workforce.get_worker("Worker").status is WorkerStatus.BUSY
    assert runtime.memory.get("latest_mission_result") is None


def test_retryable_workflow_failure_keeps_durable_ownership(db_session_factory):
    manager, workforce = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(failed_result("network timeout"))

    launch = manager.launch("Mission", "Objective", "test_workflow")
    mission, execution, worker = records(db_session_factory, launch["mission"].id)

    assert launch["result"].success is False
    assert mission.status == "RETRY_WAIT" and mission.current_worker_name == "Worker"
    assert execution.status == "QUEUED" and execution.retry_count == 1
    assert execution.max_retries == 3 and execution.next_retry_at is not None
    assert execution.failure_type is not None and execution.error == "network timeout"
    assert worker.status == "BUSY" and worker.current_mission_id == mission.id
    assert workforce.get_worker("Worker").status is WorkerStatus.BUSY


def test_exhausted_and_permanent_workflow_failures_are_terminal(db_session_factory, monkeypatch):
    manager, workforce = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(failed_result("network timeout"))
    task = Task("test_workflow", {}, max_retries=3)
    task.retry_count = 2
    monkeypatch.setattr(manager.scheduler, "schedule", lambda *args: task)
    monkeypatch.setattr(manager.scheduler, "next_task", lambda: task)

    launch = manager.launch("Mission", "Objective", "test_workflow")
    mission, execution, worker = records(db_session_factory, launch["mission"].id)

    assert task.status == "FAILED" and task.retry_count == 3
    assert mission.status == "FAILED" and mission.current_worker_name is None
    assert execution.status == "FAILED" and execution.next_retry_at is None
    assert worker.status == "ONLINE" and worker.current_mission_id is None
    assert worker.missions_failed == 1 and workforce.get_worker("Worker").status is WorkerStatus.ONLINE


def test_permanent_workflow_failure_is_not_scheduled_for_retry(db_session_factory):
    manager, _ = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(failed_result("validation error"))

    launch = manager.launch("Mission", "Objective", "test_workflow")
    mission, execution, worker = records(db_session_factory, launch["mission"].id)

    assert mission.status == "FAILED" and mission.current_worker_name is None
    assert execution.status == "FAILED" and execution.retry_count == 0
    assert execution.error == "validation error" and worker.missions_failed == 1


def test_retryable_python_exception_uses_existing_executor_contract(db_session_factory):
    manager, workforce = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(error=RuntimeError("network timeout"))

    launch = manager.launch("Mission", "Objective", "test_workflow")
    mission, execution, worker = records(db_session_factory, launch["mission"].id)

    assert mission.status == "RETRY_WAIT" and execution.status == "QUEUED"
    assert worker.status == "BUSY" and workforce.get_worker("Worker").status is WorkerStatus.BUSY
    # TaskExecutor returns None for a scheduled exception retry, so this is the
    # best metadata currently available to MissionManager without changing it.
    assert execution.error == "Mission execution failed." and execution.failure_type == "UNKNOWN"


def test_terminal_python_exception_cleans_up_then_reraises(db_session_factory, monkeypatch):
    manager, workforce = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(error=RuntimeError("validation error"))
    task = Task("test_workflow", {}, max_retries=3)
    task.retry_count = 2
    monkeypatch.setattr(manager.scheduler, "schedule", lambda *args: task)
    monkeypatch.setattr(manager.scheduler, "next_task", lambda: task)

    with pytest.raises(RuntimeError, match="validation error"):
        manager.launch("Mission", "Objective", "test_workflow")

    mission, execution, worker = records(db_session_factory, manager.missions()[0].id)
    assert mission.status == "FAILED" and mission.current_worker_name is None
    assert execution.status == "FAILED" and execution.error == "validation error"
    assert worker.status == "ONLINE" and worker.missions_failed == 1
    assert workforce.get_worker("Worker").status is WorkerStatus.ONLINE


@pytest.mark.parametrize(
    "worker, capability",
    [
        (None, None),
        (WorkerInfo("Offline", "Test"), None),
        (online_worker(capabilities=["other"]), "required"),
    ],
)
def test_unavailable_workers_wait_without_executing(db_session_factory, worker, capability):
    workers = [] if worker is None else [worker]
    manager, _ = make_manager(db_session_factory, workers)
    engine = Engine(successful_result())
    manager.executor.engine = engine

    launch = manager.launch("Mission", "Objective", "test_workflow", required_capability=capability)
    mission, execution, _ = records(db_session_factory, launch["mission"].id)

    assert launch["worker"] is None and launch["result"] is None
    assert mission.status == "WAITING_FOR_WORKER" and execution is None and engine.calls == 0


def test_failed_durable_claim_uses_next_eligible_worker(db_session_factory, monkeypatch):
    first, second = online_worker("First"), online_worker("Second")
    manager, _ = make_manager(db_session_factory, [first, second])
    manager.executor.engine = Engine(successful_result())
    original_claim = WorkerRepository.claim

    def claim(repository, worker_name, mission_id):
        return False if worker_name == "First" else original_claim(repository, worker_name, mission_id)

    monkeypatch.setattr(WorkerRepository, "claim", claim)
    launch = manager.launch("Mission", "Objective", "test_workflow")

    assert launch["worker"].name == "Second"
    session = db_session_factory()
    try:
        first_record = session.get(Worker, "First")
        second_record = session.get(Worker, "Second")
        assert first_record.status == "ONLINE" and second_record.missions_completed == 1
    finally:
        session.close()


@pytest.mark.parametrize("state", ["COMPLETED", "FAILED", "RETRY_WAIT", "WAITING_FOR_WORKER", "ASSIGNED"])
def test_duplicate_idempotency_never_relaunches_existing_state(db_session_factory, state):
    worker = online_worker()
    manager, _ = make_manager(db_session_factory, [worker])
    engine = Engine(successful_result() if state == "COMPLETED" else failed_result("validation error"))
    manager.executor.engine = engine
    key = f"same-key-{state}"

    if state == "WAITING_FOR_WORKER":
        manager, _ = make_manager(db_session_factory)
        manager.executor.engine = engine
        first = manager.launch("Mission", "Objective", "test_workflow", idempotency_key=key)
    elif state == "ASSIGNED":
        mission = manager.create_mission("Mission", "Objective", "test_workflow", idempotency_key=key)
        session = db_session_factory()
        try:
            MissionRepository(session).update_status(mission.id, MissionStatus.ASSIGNED, current_worker_name="Worker")
        finally:
            session.close()
        first = {"mission": mission}
    elif state == "RETRY_WAIT":
        manager.executor.engine = Engine(failed_result("network timeout"))
        first = manager.launch("Mission", "Objective", "test_workflow", idempotency_key=key)
        engine = manager.executor.engine
    else:
        first = manager.launch("Mission", "Objective", "test_workflow", idempotency_key=key)

    duplicate = manager.launch("Mission", "Objective", "test_workflow", idempotency_key=key)
    session = db_session_factory()
    try:
        assert session.query(MissionRecord).filter(MissionRecord.idempotency_key == key).count() == 1
        assert session.query(Execution).filter(Execution.mission_id == first["mission"].id).count() == (0 if state in {"WAITING_FOR_WORKER", "ASSIGNED"} else 1)
    finally:
        session.close()
    assert duplicate["mission"].id == first["mission"].id
    assert duplicate["worker"] is None and duplicate["result"] is None
    assert engine.calls == (0 if state in {"WAITING_FOR_WORKER", "ASSIGNED"} else 1)


def test_new_manager_and_ensure_preserve_existing_durable_busy_worker(db_session_factory):
    session = db_session_factory()
    try:
        repository = WorkerRepository(session)
        repository.create("Worker", "Test", status=WorkerStatus.ONLINE)
        assert repository.claim("Worker", "existing-mission") is True
        worker = repository.get_by_name("Worker")
        worker.missions_completed = 4
        worker.missions_failed = 1
        session.commit()
    finally:
        session.close()

    manager, _ = make_manager(db_session_factory, [online_worker()])
    manager.executor.engine = Engine(successful_result())
    launch = manager.launch("Mission", "Objective", "test_workflow")
    durable, execution, worker = records(db_session_factory, launch["mission"].id)

    assert durable.status == "WAITING_FOR_WORKER" and execution is None
    assert worker.status == "BUSY" and worker.current_mission_id == "existing-mission"
    assert worker.missions_completed == 4 and worker.missions_failed == 1


def test_successful_operation_closes_its_session(db_session_factory):
    sessions = []

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
        session = TrackedSession()
        sessions.append(session)
        return session

    manager, _ = make_manager(factory)
    manager.create_mission("Mission", "Objective", "test_workflow")

    assert len(sessions) == 1 and sessions[0].closed is True
