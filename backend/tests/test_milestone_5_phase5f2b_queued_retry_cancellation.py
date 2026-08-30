"""Focused proofs for cancelling only coherent queued distribution retries."""

import pytest

from app.distribution.contracts import DistributionFailureCategory
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.services.queued_retry_cancellation_service import QueuedRetryCancellationService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from tests.test_milestone_5_phase5d_distribution_mission import setup


def queued_retry(db, factory):
    run, fake, launcher, _manager, _workflow = setup(
        db, factory, outcome=DistributionFailureCategory.RATE_LIMIT,
    )
    launched = launcher.launch(run.id)
    return run, fake, launched.mission_id


def test_cancel_queued_retry_terminalizes_without_worker_metrics(db_session, db_session_factory):
    run, fake, mission_id = queued_retry(db_session, db_session_factory)
    worker = db_session.get(Worker, "Content Writer")
    metrics = (worker.missions_completed, worker.missions_failed)
    cancelled = QueuedRetryCancellationService(db_session_factory).cancel(run.id)
    db_session.expire_all()
    mission = db_session.get(MissionRecord, mission_id)
    execution = db_session.query(Execution).filter_by(mission_id=mission_id).one()
    worker = db_session.get(Worker, "Content Writer")
    assert cancelled.status == "CANCELLED" and mission.status == execution.status == "FAILED"
    assert execution.next_retry_at is execution.lease_owner is execution.lease_expires_at is None
    assert execution.failure_type == "OPERATOR_CANCELLED" and "Operator cancelled" in execution.error
    assert (worker.status, worker.current_mission_id, worker.missions_completed, worker.missions_failed) == ("ONLINE", None, *metrics)
    assert fake.publish_calls == 1


def test_repeat_cancel_is_idempotent_and_scanner_and_recovery_do_nothing(db_session, db_session_factory):
    run, _fake, mission_id = queued_retry(db_session, db_session_factory)
    service = QueuedRetryCancellationService(db_session_factory)
    assert service.cancel(run.id).status == service.cancel(run.id).status == "CANCELLED"
    execution = db_session.query(Execution).filter_by(mission_id=mission_id).one()
    scanner = RetryScanner(ExecutionService(ExecutionRepository(db_session)), Scheduler())
    assert scanner.scan_once() == []
    assert RunningExecutionRecoveryService(db_session_factory).recover(execution.id) is None
    assert db_session.query(Execution).filter_by(mission_id=mission_id).count() == 1


@pytest.mark.parametrize("mutation", ["mission", "execution", "worker", "lease"])
def test_corrupt_or_active_retry_is_rejected_without_partial_mutation(db_session, db_session_factory, mutation):
    run, _fake, mission_id = queued_retry(db_session, db_session_factory)
    execution = db_session.query(Execution).filter_by(mission_id=mission_id).one()
    if mutation == "mission":
        db_session.get(MissionRecord, mission_id).status = "COMPLETED"
    elif mutation == "execution":
        execution.status = "RETRYING"
    elif mutation == "worker":
        db_session.get(Worker, "Content Writer").current_mission_id = "other"
    else:
        execution.lease_owner = "unexpected"
    db_session.commit()
    with pytest.raises(ValueError, match="coherent queued retry"):
        QueuedRetryCancellationService(db_session_factory).cancel(run.id)
    db_session.expire_all()
    assert db_session.get(type(run), run.id).status == "RETRY_WAIT"


def test_cancelled_retry_worker_is_reusable(db_session, db_session_factory):
    run, _fake, mission_id = queued_retry(db_session, db_session_factory)
    QueuedRetryCancellationService(db_session_factory).cancel(run.id)
    from app.repositories.worker_repository import WorkerRepository
    assert WorkerRepository(db_session).claim("Content Writer", "next-mission")
    db_session.expire_all()
    assert db_session.get(Worker, "Content Writer").current_mission_id == "next-mission"
