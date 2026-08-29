"""Focused transaction proofs for distribution safe-retry scheduling."""

import pytest
from datetime import datetime, timedelta, timezone

from app.distribution.contracts import DistributionFailureCategory
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.execution_service import ExecutionService
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from tests.test_milestone_5_phase5d_distribution_mission import setup


def state(db, run, mission_id):
    db.expire_all()
    return (
        db.get(type(run), run.id),
        db.get(MissionRecord, mission_id),
        db.query(Execution).filter_by(mission_id=mission_id).one(),
        db.get(Worker, "Content Writer"),
    )


@pytest.mark.parametrize("category", [
    DistributionFailureCategory.RATE_LIMIT,
    DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT,
    DistributionFailureCategory.PROVIDER_UNAVAILABLE,
])
def test_safe_failures_atomically_schedule_distribution_retry(db_session, db_session_factory, category):
    run, _, launcher, _, _ = setup(db_session, db_session_factory, outcome=category)
    launched = launcher.launch(run.id)
    row, mission, execution, worker = state(db_session, run, launched.mission_id)
    assert (row.status, execution.status, mission.status) == ("RETRY_WAIT", "QUEUED", "RETRY_WAIT")
    assert execution.next_retry_at is not None and execution.lease_expires_at is None
    assert worker.status == "BUSY" and worker.current_mission_id == mission.id


def test_fault_before_lifecycle_commit_rolls_back_business_retry_transition(db_session, db_session_factory, monkeypatch):
    run, _, launcher, _, _ = setup(db_session, db_session_factory, outcome=DistributionFailureCategory.RATE_LIMIT)
    original = DistributionRunRepository.transition_owned
    def fault_before_commit(self, *args, **kwargs):
        if kwargs["status"] == "RETRY_WAIT":
            raise RuntimeError("fault before commit")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(DistributionRunRepository, "transition_owned", fault_before_commit)
    with pytest.raises(RuntimeError, match="fault before commit"):
        launcher.launch(run.id)
    db_session.expire_all()
    row = db_session.get(type(run), run.id)
    execution = db_session.query(Execution).one()
    mission = db_session.get(MissionRecord, execution.mission_id)
    assert (row.status, execution.status, mission.status) == ("PUBLISHING", "RUNNING", "RUNNING")


def test_fault_after_execution_mutation_rolls_back_entire_retry_transaction(db_session, db_session_factory, monkeypatch):
    run, _, launcher, _, _ = setup(db_session, db_session_factory, outcome=DistributionFailureCategory.RATE_LIMIT)
    monkeypatch.setattr(OwnedExecutionLifecycleCoordinator, "_mission_update", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fault after lifecycle mutation")))
    with pytest.raises(RuntimeError, match="fault after lifecycle mutation"):
        launcher.launch(run.id)
    db_session.expire_all()
    row = db_session.get(type(run), run.id)
    execution = db_session.query(Execution).one()
    mission = db_session.get(MissionRecord, execution.mission_id)
    assert (row.status, execution.status, mission.status) == ("PUBLISHING", "RUNNING", "RUNNING")


def test_final_retry_exhaustion_terminalizes_distribution_run(db_session, db_session_factory):
    run, _, launcher, manager, _ = setup(db_session, db_session_factory, outcome=DistributionFailureCategory.RATE_LIMIT)
    launched = launcher.launch(run.id)
    execution = db_session.query(Execution).filter_by(mission_id=launched.mission_id).one()
    execution.retry_count = execution.max_retries - 1
    execution.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    service = ExecutionService(ExecutionRepository(db_session))
    task = RetryScanner(service, Scheduler()).scan_once()[0]
    from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
    RetryLifecycleCoordinator(db_session, service, MissionRepository(db_session), WorkerRepository(db_session), manager.workforce, manager.executor).execute(task)
    row, mission, execution, worker = state(db_session, run, launched.mission_id)
    assert (row.status, execution.status, mission.status) == ("FAILED", "FAILED", "FAILED")
    assert execution.next_retry_at is None and worker.status == "ONLINE"
