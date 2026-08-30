"""Focused durable proofs for due scheduled distribution activation."""

from datetime import datetime, timedelta, timezone

from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.worker_repository import WorkerRepository
from app.services.distribution_run_service import DistributionRunService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.scheduled_distribution_activation_service import ScheduledDistributionActivationService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request, source


def scheduled_run(db, when):
    source(db)
    run = DistributionRunService(db).create(request(scheduled_for=when))
    assert run.status == "SCHEDULED"
    return run


def add_worker(db):
    return WorkerRepository(db).create("Scheduler Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)


def test_future_schedule_is_not_activated(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    assert ScheduledDistributionActivationService(db_session_factory).scan_once() == []
    assert db_session.get(DistributionRun, run.id).status == "SCHEDULED"
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


def test_due_schedule_activates_original_identity_with_business_payload(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(seconds=1))
    run.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit(); add_worker(db_session)
    dispatched = []
    activated = ScheduledDistributionActivationService(db_session_factory, dispatch=dispatched.append).scan_once()
    db_session.expire_all()
    mission = db_session.query(MissionRecord).one(); execution = db_session.query(Execution).one(); worker = db_session.get(Worker, "Scheduler Worker")
    assert len(activated) == len(dispatched) == 1
    assert db_session.get(DistributionRun, run.id).status == "CREATED"
    assert mission.status == execution.status == "RUNNING"
    assert mission.idempotency_key == f"distribution:{run.id}" and mission.input_data == '{"distribution_run_id": "%s"}' % run.id
    assert execution.status == "RUNNING" and execution.lease_owner and execution.lease_generation == 1 and execution.lease_expires_at
    assert (worker.status, worker.current_mission_id) == ("BUSY", mission.id)


def test_no_worker_rolls_back_due_activation(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(seconds=1))
    run.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1); db_session.commit()
    assert ScheduledDistributionActivationService(db_session_factory).scan_once() == []
    db_session.expire_all()
    assert db_session.get(DistributionRun, run.id).status == "SCHEDULED"
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


def test_repeat_scan_and_future_row_do_not_duplicate_activation(db_session, db_session_factory):
    due = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(seconds=1))
    due.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1); db_session.commit()
    future = DistributionRunService(db_session).create(request(destination="other", scheduled_for=datetime.now(timezone.utc) + timedelta(hours=1)))
    add_worker(db_session)
    scanner = ScheduledDistributionActivationService(db_session_factory)
    assert len(scanner.scan_once()) == 1 and scanner.scan_once() == []
    db_session.expire_all()
    assert db_session.get(DistributionRun, due.id).status == "CREATED" and db_session.get(DistributionRun, future.id).status == "SCHEDULED"
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 1


def test_committed_undispatched_scheduled_operation_recovers(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(seconds=1))
    run.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1); db_session.commit(); add_worker(db_session)
    operation = ScheduledDistributionActivationService(db_session_factory).scan_once()[0]
    db_session.execute(__import__("sqlalchemy").text("UPDATE executions SET lease_expires_at = :expired WHERE id = :id"), {"expired": datetime.now(timezone.utc) - timedelta(minutes=1), "id": operation.execution_id}); db_session.commit()
    recovered = RunningExecutionRecoveryService(db_session_factory).recover(operation.execution_id)
    assert recovered and recovered.mission_id == operation.mission_id and recovered.authority.lease_generation == 2
