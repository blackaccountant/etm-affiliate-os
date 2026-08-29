"""Focused proofs for leased retry claims and Phase 3R recovery."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5d_distribution_mission import setup


def seed(db):
    missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
    mission = missions.create("retry-mission", "Retry", "proof", "retry_proof", input_data={"value": 1}, current_worker_name="Retry Worker")
    missions.update_status(mission.id, "RETRY_WAIT", current_worker_name="Retry Worker")
    workers.create("Retry Worker", "Test", ["retry"], WorkerStatus.ONLINE)
    assert workers.claim("Retry Worker", mission.id)
    execution = executions.create("retry_proof", "QUEUED", mission.id, mission.name, "Retry Worker", input_data='{"value": 1}', retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    return mission, execution


def claim(db):
    service = ExecutionService(ExecutionRepository(db))
    tasks = RetryScanner(service, Scheduler()).scan_once()
    assert len(tasks) == 1
    return tasks[0], tasks[0].execution_authority


def test_due_claim_commits_leased_active_attempt_and_no_second_claim(db_session):
    mission, execution = seed(db_session)
    task, authority = claim(db_session)
    current = db_session.get(Execution, execution.id)
    assert current.status == "RETRYING" and current.next_retry_at is None
    assert (current.lease_owner, current.lease_generation) == (authority.lease_owner, authority.lease_generation)
    expiry = current.lease_expires_at.replace(tzinfo=timezone.utc) if current.lease_expires_at.tzinfo is None else current.lease_expires_at
    assert expiry > datetime.now(timezone.utc)
    assert db_session.get(MissionRecord, mission.id).status == "RUNNING"
    assert db_session.get(Worker, "Retry Worker").current_mission_id == mission.id
    assert RetryScanner(ExecutionService(ExecutionRepository(db_session)), Scheduler()).scan_once() == []


def test_unexpired_and_expired_retrying_use_generic_phase3r_recovery(db_session, db_session_factory):
    mission, execution = seed(db_session)
    _, authority = claim(db_session)
    assert RunningExecutionRecoveryService(db_session_factory).recover(execution.id) is None
    db_session.execute(__import__("sqlalchemy").text("UPDATE executions SET lease_expires_at = :expired WHERE id = :id"), {"expired": datetime.now(timezone.utc) - timedelta(minutes=1), "id": execution.id})
    db_session.commit()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(execution.id)
    assert recovered is not None
    db_session.expire_all()
    attempts = db_session.query(Execution).filter_by(mission_id=mission.id).order_by(Execution.id).all()
    assert attempts[0].status == "ABANDONED" and len(attempts) == 2
    assert recovered.authority.lease_generation == authority.lease_generation + 1
    assert RunningExecutionRecoveryService(db_session_factory).recover(execution.id) is None


def test_heartbeat_renews_scanner_authority_and_stale_owner_is_fenced(db_session, db_session_factory):
    _, execution = seed(db_session)
    _, authority = claim(db_session)
    before = db_session.get(Execution, execution.id).lease_expires_at
    assert ExecutionRepository(db_session).renew_lease(authority, 120)
    db_session.expire_all()
    assert db_session.get(Execution, execution.id).lease_expires_at > before
    assert RunningExecutionRecoveryService(db_session_factory).recover(execution.id) is None
    stale = type(authority)(authority.execution_id, authority.lease_owner, authority.lease_generation - 1)
    with pytest.raises(ExecutionLeaseLostError):
        ExecutionRepository(db_session).fail_owned(stale, error="stale")


def test_scanner_death_before_distribution_retry_dispatch_recovers_and_resumes(db_session, db_session_factory):
    run, fake, launcher, manager, _ = setup(db_session, db_session_factory, outcome=__import__("app.distribution.contracts", fromlist=["DistributionFailureCategory"]).DistributionFailureCategory.RATE_LIMIT)
    first = launcher.launch(run.id)
    execution = db_session.query(Execution).filter_by(mission_id=first.mission_id).one()
    execution.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    _, authority = claim(db_session)
    db_session.execute(__import__("sqlalchemy").text("UPDATE executions SET lease_expires_at = :expired WHERE id = :id"), {"expired": datetime.now(timezone.utc) - timedelta(minutes=1), "id": execution.id})
    db_session.commit()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(execution.id)
    assert recovered is not None
    fake.outcome = None
    result = manager.resume_recovered_mission(recovered)
    db_session.expire_all()
    assert result.success and db_session.get(type(run), run.id).status == "COMPLETED"
    attempts = db_session.query(Execution).filter_by(mission_id=first.mission_id).order_by(Execution.id).all()
    assert attempts[0].status == "ABANDONED" and attempts[1].lease_generation == authority.lease_generation + 1
