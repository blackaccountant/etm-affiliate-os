"""Focused runtime/fencing proof for the shared owned execution lifecycle."""

from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.executor.executor import TaskExecutor
from app.mission.manager import MissionManager
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.execution_lease import ExecutionLeaseAuthority, ExecutionLeaseHeartbeat
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.execution_service import ExecutionService
from app.scheduler.scheduler import Scheduler
from app.task_queue.task import Task
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


class Engine:
    def __init__(self, result=None, started=None, release=None):
        self.result = result
        self.started = started
        self.release = release
        self.calls = 0

    def run(self, workflow_name, payload):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(5)
        return self.result


def manager_for(factory, engine):
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Lease Worker", "Test", capabilities=["lease"], status=WorkerStatus.ONLINE))
    manager = MissionManager(workforce=workforce, session_factory=factory)
    manager.executor.engine = engine
    return manager, workforce


def state(factory):
    db = factory()
    try:
        return db.query(MissionRecord).one(), db.query(Execution).one(), db.query(Worker).one()
    finally:
        db.close()


def test_initial_runtime_acquires_lease_before_workflow_and_finalizes_atomically(db_session_factory):
    observed = {}

    class InspectingEngine(Engine):
        def run(self, workflow_name, payload):
            db = db_session_factory()
            try:
                execution = db.query(Execution).one()
                observed.update(owner=execution.lease_owner, generation=execution.lease_generation,
                                expires=execution.lease_expires_at)
            finally:
                db.close()
            return super().run(workflow_name, payload)

    manager, workforce = manager_for(db_session_factory, InspectingEngine({"success": True, "errors": []}))
    launched = manager.launch("Lease mission", "prove lifecycle", "lease_workflow", {}, "lease")
    mission, execution, worker = state(db_session_factory)
    assert launched["result"].success is True
    assert observed["owner"] and observed["generation"] == 1 and observed["expires"] is not None
    assert (execution.status, mission.status, worker.status) == ("COMPLETED", "COMPLETED", "ONLINE")
    assert execution.lease_owner is None and execution.lease_expires_at is None
    assert worker.current_mission_id is None and workforce.get_worker("Lease Worker").status is WorkerStatus.ONLINE


def test_blocked_workflow_heartbeat_renews_with_independent_sessions(db_session_factory, monkeypatch):
    started, release = Event(), Event()
    engine = Engine({"success": True, "errors": []}, started=started, release=release)
    manager, _ = manager_for(db_session_factory, engine)
    original = ExecutionLeaseHeartbeat

    def fast_heartbeat(factory, authority, lease_seconds=None, heartbeat_seconds=None):
        return original(factory, authority, lease_seconds=.30, heartbeat_seconds=.05)

    monkeypatch.setattr("app.services.execution_attempt_runner.ExecutionLeaseHeartbeat", fast_heartbeat)
    thread = Thread(target=lambda: manager.launch("Blocked", "prove heartbeat", "lease_workflow", {}, "lease"))
    thread.start()
    assert started.wait(3)
    sleep(.09)
    _, first, _ = state(db_session_factory)
    sleep(.10)
    _, second, _ = state(db_session_factory)
    assert first.lease_owner and second.lease_owner == first.lease_owner
    assert second.lease_expires_at > first.lease_expires_at
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    mission, execution, worker = state(db_session_factory)
    assert (mission.status, execution.status, worker.status) == ("COMPLETED", "COMPLETED", "ONLINE")


@pytest.mark.parametrize("result, expected_error", [
    ({"success": True, "errors": []}, None),
    ({"success": False, "errors": ["invalid payload"]}, "invalid payload"),
    ({"success": False, "errors": ["network timeout"]}, "network timeout"),
])
def test_stale_runtime_cannot_finalize_or_mutate_metadata(db_session_factory, result, expected_error):
    started, release = Event(), Event()
    manager, _ = manager_for(db_session_factory, Engine(result, started=started, release=release))
    outcome = {}
    thread = Thread(target=lambda: outcome.setdefault(
        "launch", manager.launch("Stale", "prove fence", "lease_workflow", {}, "lease")
    ))
    thread.start()
    assert started.wait(3)
    db = db_session_factory()
    try:
        execution = db.query(Execution).one()
        db.execute(update(Execution).where(Execution.id == execution.id).values(
            lease_owner="replacement", lease_generation=execution.lease_generation + 1,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        ))
        db.commit()
    finally:
        db.close()
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    mission, execution, worker = state(db_session_factory)
    assert execution.status == "RUNNING"
    assert execution.lease_owner == "replacement" and execution.result_data is None
    assert mission.status == "RUNNING" and worker.status == "BUSY"
    assert worker.current_mission_id == mission.id


def seed_active(factory):
    db = factory()
    try:
        missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
        mission = missions.create(str(uuid4()), "Owned", "prove transaction", "lease_workflow", current_worker_name="Lease Worker")
        missions.update_status(mission.id, "RUNNING", current_worker_name="Lease Worker")
        workers.create("Lease Worker", "Test", ["lease"], WorkerStatus.ONLINE)
        assert workers.claim("Lease Worker", mission.id)
        execution = executions.create("lease_workflow", "RUNNING", mission.id, mission.name, "Lease Worker")
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        assert executions.acquire_lease(authority, 60)
        return mission.id, mission.name, authority
    finally:
        db.close()


def test_owned_failure_transition_is_coherent(db_session_factory):
    mission_id, mission_name, authority = seed_active(db_session_factory)
    db = db_session_factory()
    try:
        coordinator = OwnedExecutionLifecycleCoordinator(db)
        coordinator.fail(authority, mission_id=mission_id, mission_name=mission_name, worker_name="Lease Worker",
                         duration=.1, result_data='{"success": false}', result_payload={"success": False},
                         error="invalid payload", failure_type="VALIDATION", retry_count=0)
    finally:
        db.close()
    durable_mission, execution, worker = state(db_session_factory)
    assert (execution.status, durable_mission.status, worker.status) == ("FAILED", "FAILED", "ONLINE")
    assert execution.lease_owner is None and execution.lease_expires_at is None and execution.next_retry_at is None
    assert execution.lease_generation == authority.lease_generation
    db = db_session_factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            ExecutionRepository(db).verify_active_authority(authority)
    finally:
        db.close()


def test_owned_completion_clears_lease_and_fences_original_authority(db_session_factory):
    mission_id, _, authority = seed_active(db_session_factory)
    db = db_session_factory()
    try:
        before = db.get(Execution, authority.execution_id)
        assert before.lease_owner == authority.lease_owner and before.lease_expires_at is not None
        generation = before.lease_generation
        completed = ExecutionRepository(db).complete_owned(authority, result_data='{"success": true}')
        assert completed.status == "COMPLETED"
        assert completed.lease_owner is None and completed.lease_expires_at is None
        assert completed.lease_generation == generation
    finally:
        db.close()
    db = db_session_factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            ExecutionRepository(db).verify_active_authority(authority)
    finally:
        db.close()


def test_owned_retry_transition_is_coherent(db_session_factory):
    mission_id, mission_name, authority = seed_active(db_session_factory)
    db = db_session_factory()
    try:
        coordinator = OwnedExecutionLifecycleCoordinator(db)
        coordinator.schedule_retry(authority, mission_id=mission_id, mission_name=mission_name, worker_name="Lease Worker",
                                   result_data='{"success": false}', result_payload={"success": False},
                                   retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc),
                                   error="network timeout", failure_type="NETWORK")
    finally:
        db.close()
    durable_mission, execution, worker = state(db_session_factory)
    assert (execution.status, durable_mission.status, worker.status) == ("QUEUED", "RETRY_WAIT", "BUSY")
    assert worker.current_mission_id == durable_mission.id and execution.lease_owner is None


def test_failed_execution_fence_rolls_back_mission_and_worker(db_session_factory):
    mission_id, mission_name, authority = seed_active(db_session_factory)
    stale = ExecutionLeaseAuthority(authority.execution_id, authority.lease_owner, authority.lease_generation + 1)
    db = db_session_factory()
    try:
        coordinator = OwnedExecutionLifecycleCoordinator(db)
        with pytest.raises(Exception):
            coordinator.complete(stale, mission_id=mission_id, mission_name=mission_name, worker_name="Lease Worker",
                                 duration=.1, result_data='{}', result_payload={"success": True})
    finally:
        db.close()
    durable_mission, execution, worker = state(db_session_factory)
    assert (execution.status, durable_mission.status, worker.status) == ("RUNNING", "RUNNING", "BUSY")
    assert execution.result_data is None and worker.current_mission_id == durable_mission.id


def test_claimed_retry_uses_the_same_leased_attempt_runtime(db_session_factory):
    db = db_session_factory()
    try:
        missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
        mission = missions.create(str(uuid4()), "Retry", "prove retry", "lease_workflow", current_worker_name="Lease Worker")
        missions.update_status(mission.id, "RETRY_WAIT", current_worker_name="Lease Worker")
        workers.create("Lease Worker", "Test", ["lease"], WorkerStatus.ONLINE)
        assert workers.claim("Lease Worker", mission.id)
        execution = executions.create(
            "lease_workflow", "QUEUED", mission.id, mission.name, "Lease Worker",
            input_data="{}", retry_count=1, max_retries=3,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        claimed = executions.claim_due_retry(execution.id)
        assert claimed is not None
        task = Task("lease_workflow", {
            "execution_id": execution.id, "mission_id": mission.id,
            "worker_name": "Lease Worker",
        })
        task.retry_count = 1
        task.max_retries = 3
        task.execution_authority = claimed.retry_authority
        observed = {}

        class RetryEngine(Engine):
            def run(self, workflow_name, payload):
                probe = db_session_factory()
                try:
                    active = probe.get(Execution, execution.id)
                    observed.update(owner=active.lease_owner, generation=active.lease_generation)
                finally:
                    probe.close()
                return super().run(workflow_name, payload)

        executor = TaskExecutor(execution_service=ExecutionService(executions))
        executor.engine = RetryEngine({"success": True, "errors": []})
        workforce = WorkforceManager()
        coordinator = RetryLifecycleCoordinator(
            db, ExecutionService(executions), missions, workers, workforce, executor,
            session_factory=db_session_factory,
        )
        assert coordinator.execute(task) == {"success": True, "errors": []}
    finally:
        db.close()
    durable_mission, durable_execution, worker = state(db_session_factory)
    assert observed["owner"] and observed["generation"] == 1
    assert (durable_mission.status, durable_execution.status, worker.status) == ("COMPLETED", "COMPLETED", "ONLINE")
