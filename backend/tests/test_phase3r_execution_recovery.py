"""Focused abandoned-execution recovery proofs using isolated SQLite state."""

from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import sleep

import pytest
from sqlalchemy import update

from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.mission.manager import MissionManager
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


class Engine:
    def __init__(self, result):
        self.result = result

    def run(self, workflow_name, payload):
        return self.result


def manager_for(factory, engine):
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Lease Worker", "Test", capabilities=["lease"], status=WorkerStatus.ONLINE))
    manager = MissionManager(workforce=workforce, session_factory=factory)
    manager.executor.engine = engine
    return manager, workforce


def seed_active(factory):
    db = factory()
    try:
        missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
        mission = missions.create(str(__import__("uuid").uuid4()), "Owned", "prove recovery", "lease_workflow", current_worker_name="Lease Worker")
        missions.update_status(mission.id, "RUNNING", current_worker_name="Lease Worker")
        workers.create("Lease Worker", "Test", ["lease"], WorkerStatus.ONLINE)
        assert workers.claim("Lease Worker", mission.id)
        execution = executions.create("lease_workflow", "RUNNING", mission.id, mission.name, "Lease Worker", input_data="{}")
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        assert executions.acquire_lease(authority, 60)
        return mission.id, mission.name, authority
    finally:
        db.close()


def expire(factory, execution_id):
    db = factory()
    try:
        db.execute(update(Execution).where(Execution.id == execution_id).values(
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        ))
        db.commit()
    finally:
        db.close()


def durable(factory, mission_id, first_id):
    db = factory()
    try:
        mission = db.get(MissionRecord, mission_id)
        first = db.get(Execution, first_id)
        attempts = db.query(Execution).filter(Execution.mission_id == mission_id).order_by(Execution.id).all()
        worker = db.get(Worker, "Lease Worker")
        return mission, first, attempts, worker
    finally:
        db.close()


def test_expired_execution_is_abandoned_and_replaced_once(db_session_factory):
    mission_id, _, authority = seed_active(db_session_factory)
    expire(db_session_factory, authority.execution_id)
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(authority.execution_id)
    assert recovered is not None
    mission, first, attempts, worker = durable(db_session_factory, mission_id, authority.execution_id)
    assert mission.status == "RUNNING" and mission.id == recovered.mission_id
    assert len(attempts) == 2 and first.status == "ABANDONED"
    second = attempts[1]
    assert second.id == recovered.replacement_execution_id
    assert second.lease_generation == first.lease_generation + 1
    assert second.lease_owner and second.lease_owner != first.lease_owner
    assert second.lease_expires_at is not None and first.lease_expires_at is None
    assert worker.status == WorkerStatus.BUSY.value and worker.current_mission_id == mission_id
    assert RunningExecutionRecoveryService(db_session_factory).recover(authority.execution_id) is None
    assert len(durable(db_session_factory, mission_id, authority.execution_id)[2]) == 2


def test_unexpired_execution_cannot_be_recovered(db_session_factory):
    mission_id, _, authority = seed_active(db_session_factory)
    assert RunningExecutionRecoveryService(db_session_factory).recover(authority.execution_id) is None
    mission, first, attempts, worker = durable(db_session_factory, mission_id, authority.execution_id)
    assert (first.status, mission.status, worker.status) == ("RUNNING", "RUNNING", "BUSY")
    assert len(attempts) == 1


def test_blocked_heartbeat_protected_attempt_cannot_be_recovered(db_session_factory, monkeypatch):
    from app.services.execution_lease import ExecutionLeaseHeartbeat

    started, release = Event(), Event()

    class BlockingEngine:
        def run(self, workflow_name, payload):
            started.set()
            assert release.wait(5)
            return {"success": True, "errors": []}

    original = ExecutionLeaseHeartbeat
    monkeypatch.setattr(
        "app.services.execution_attempt_runner.ExecutionLeaseHeartbeat",
        lambda factory, authority, lease_seconds=None, heartbeat_seconds=None:
        original(factory, authority, lease_seconds=.30, heartbeat_seconds=.05),
    )
    manager, _ = manager_for(db_session_factory, BlockingEngine())
    thread = Thread(target=lambda: manager.launch("Blocked", "heartbeat", "lease_workflow", {}, "lease"))
    thread.start()
    assert started.wait(3)
    sleep(.12)
    db = db_session_factory()
    try:
        execution = db.query(Execution).one()
        assert RunningExecutionRecoveryService(db_session_factory).recover(execution.id) is None
    finally:
        db.close()
    release.set()
    thread.join(5)
    assert not thread.is_alive()


def test_stale_abandoned_owner_cannot_terminalize_after_recovery(db_session_factory):
    mission_id, _, authority = seed_active(db_session_factory)
    expire(db_session_factory, authority.execution_id)
    assert RunningExecutionRecoveryService(db_session_factory).recover(authority.execution_id)
    db = db_session_factory()
    try:
        repository = ExecutionRepository(db)
        with pytest.raises(ExecutionLeaseLostError):
            repository.complete_owned(authority, result_data='{"stale": true}')
        with pytest.raises(ExecutionLeaseLostError):
            repository.fail_owned(authority, error="stale")
        with pytest.raises(ExecutionLeaseLostError):
            repository.schedule_retry_owned(authority, retry_count=1, max_retries=3,
                                            next_retry_at=datetime.now(timezone.utc))
    finally:
        db.close()
    mission, first, attempts, worker = durable(db_session_factory, mission_id, authority.execution_id)
    assert first.status == "ABANDONED" and len(attempts) == 2
    assert mission.status == "RUNNING" and worker.status == "BUSY"


@pytest.mark.parametrize("result, expected", [
    ({"success": True, "errors": []}, ("COMPLETED", "COMPLETED", "ONLINE")),
    ({"success": False, "errors": ["invalid payload"]}, ("FAILED", "FAILED", "ONLINE")),
    ({"success": False, "errors": ["network timeout"]}, ("QUEUED", "RETRY_WAIT", "BUSY")),
])
def test_replacement_dispatches_through_normal_runtime(db_session_factory, result, expected):
    mission_id, _, authority = seed_active(db_session_factory)
    expire(db_session_factory, authority.execution_id)
    observed = {}

    class RecoveryEngine(Engine):
        def run(self, workflow_name, payload):
            observed.update(recovery=payload.get("execution_recovery"),
                            recovered_id=payload.get("recovered_execution_id"))
            return super().run(workflow_name, payload)

    manager, _ = manager_for(db_session_factory, RecoveryEngine(result))
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(authority.execution_id)
    assert recovered is not None
    manager.resume_recovered_mission(recovered)
    mission, first, attempts, worker = durable(db_session_factory, mission_id, authority.execution_id)
    replacement = attempts[1]
    assert observed == {"recovery": True, "recovered_id": authority.execution_id}
    assert first.status == "ABANDONED"
    assert (replacement.status, mission.status, worker.status) == expected
