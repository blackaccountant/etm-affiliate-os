"""Focused proofs for SCHEDULED-only distribution lifecycle control."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.distribution_run import DistributionRun
from app.models.discovery import DiscoveryRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.repositories.worker_repository import WorkerRepository
from app.services.distribution_run_service import DistributionRunService
from app.services.scheduled_distribution_activation_service import ScheduledDistributionActivationService
from app.services.scheduled_distribution_cancellation_service import ScheduledDistributionCancellationService
from app.services.scheduled_distribution_rescheduling_service import ScheduledDistributionReschedulingService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request, source


def scheduled_run(db, when, destination="blog"):
    if db.get(DiscoveryRun, "discovery") is None:
        source(db)
    run = DistributionRunService(db).create(request(destination=destination, scheduled_for=when))
    assert run.status == "SCHEDULED"
    return run


def add_worker(db):
    return WorkerRepository(db).create("Scheduler Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)


def test_cancel_scheduled_is_idempotent_and_creates_no_operation(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    cancel = ScheduledDistributionCancellationService(db_session_factory)
    assert cancel.cancel(run.id).status == "CANCELLED"
    assert cancel.cancel(run.id).status == "CANCELLED"
    db_session.expire_all()
    stored = db_session.get(DistributionRun, run.id)
    assert stored.status == "CANCELLED" and stored.scheduled_for == run.scheduled_for
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


@pytest.mark.parametrize("status", ["CREATED", "RUNNING", "PUBLISHING", "RETRY_WAIT", "RECONCILIATION_REQUIRED", "RECONCILING", "COMPLETED", "FAILED"])
def test_cancel_rejects_every_non_scheduled_state(db_session, db_session_factory, status):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    run.status = status
    db_session.commit()
    with pytest.raises(ValueError, match="only scheduled"):
        ScheduledDistributionCancellationService(db_session_factory).cancel(run.id)
    db_session.expire_all()
    assert db_session.get(DistributionRun, run.id).status == status


def test_reschedule_preserves_scheduled_identity_and_generations(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    new_time = datetime.now(timezone.utc) + timedelta(hours=2)
    rescheduled = ScheduledDistributionReschedulingService(db_session_factory).reschedule(run.id, new_time)
    assert rescheduled.status == "SCHEDULED"
    db_session.expire_all()
    stored = db_session.get(DistributionRun, run.id)
    assert stored.scheduled_for == new_time and (stored.publish_generation, stored.reconciliation_generation) == (0, 0)
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 0


def test_reschedule_rejects_non_future_and_non_scheduled_runs(db_session, db_session_factory):
    run = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1))
    service = ScheduledDistributionReschedulingService(db_session_factory)
    # SQLite's CURRENT_TIMESTAMP has second precision; the guarded PostgreSQL
    # module covers the exact database-now boundary.
    for when in (datetime.now(timezone.utc) - timedelta(seconds=1), datetime.now(timezone.utc) - timedelta(minutes=1)):
        with pytest.raises(ValueError, match="strictly future"):
            service.reschedule(run.id, when)
    run.status = "CANCELLED"
    db_session.commit()
    with pytest.raises(ValueError, match="only scheduled"):
        service.reschedule(run.id, datetime.now(timezone.utc) + timedelta(hours=2))


def test_cancelled_scan_is_excluded_and_rescheduled_run_activates_once(db_session, db_session_factory):
    cancelled = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1), "cancelled")
    rescheduled = scheduled_run(db_session, datetime.now(timezone.utc) + timedelta(hours=1), "rescheduled")
    cancelled_service = ScheduledDistributionCancellationService(db_session_factory)
    cancelled_service.cancel(cancelled.id)
    db_session.get(DistributionRun, rescheduled.id).scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    new_time = datetime.now(timezone.utc) + timedelta(hours=2)
    ScheduledDistributionReschedulingService(db_session_factory).reschedule(rescheduled.id, new_time)
    assert ScheduledDistributionActivationService(db_session_factory).scan_once() == []
    db_session.get(DistributionRun, rescheduled.id).scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    add_worker(db_session)
    activated = ScheduledDistributionActivationService(db_session_factory).scan_once()
    assert len(activated) == 1 and activated[0].spec.idempotency_key == f"distribution:{rescheduled.id}"
    assert ScheduledDistributionActivationService(db_session_factory).scan_once() == []
    db_session.expire_all()
    assert db_session.get(DistributionRun, cancelled.id).status == "CANCELLED"
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 1
