"""Guarded PostgreSQL races for SCHEDULED-only lifecycle control."""

from datetime import datetime, timedelta, timezone
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.discovery import DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.repositories.worker_repository import WorkerRepository
from app.services.distribution_run_service import DistributionRunService
from app.services.scheduled_distribution_activation_service import ScheduledDistributionActivationService
from app.services.scheduled_distribution_cancellation_service import ScheduledDistributionCancellationService
from app.services.scheduled_distribution_rescheduling_service import ScheduledDistributionReschedulingService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request
from tests.test_milestone_5_phase5e2e_postgresql_operation_races import _lineage


_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (
    _url.drivername.startswith("postgresql")
    and _url.host == "127.0.0.1"
    and _url.port == 5432
    and _url.database == "etm_affiliate_os_g5_test"
):
    raise RuntimeError("Phase 5F.2A requires guarded local G5.")


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "fa1b2c3d4e5f"
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    with engine.begin() as connection:
        tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
        connection.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{name}\"' for name in tables) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _run(factory, when, destination="blog"):
    db = factory()
    try:
        if db.get(DiscoveryRun, "discovery") is None:
            _lineage(db)
        run = DistributionRunService(db).create(request(destination=destination, scheduled_for=when))
        db.commit()
        return run.id
    finally:
        db.close()


def _set_due(factory, run_id):
    db = factory()
    try:
        db.get(DistributionRun, run_id).scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()


def _worker(factory):
    db = factory()
    try:
        WorkerRepository(db).create("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)
    finally:
        db.close()


def _race(*actions):
    barrier = threading.Barrier(len(actions))
    outcomes = []

    def invoke(action):
        barrier.wait()
        try:
            outcomes.append(("ok", action()))
        except ValueError as exc:
            outcomes.append(("rejected", str(exc)))

    threads = [threading.Thread(target=invoke, args=(action,)) for action in actions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert all(not thread.is_alive() for thread in threads)
    return outcomes


def test_scheduler_vs_cancel_has_one_coherent_winner(factory):
    run_id = _run(factory, datetime.now(timezone.utc) + timedelta(seconds=1))
    _set_due(factory, run_id)
    _worker(factory)
    outcomes = _race(
        lambda: ScheduledDistributionActivationService(factory).scan_once(),
        lambda: ScheduledDistributionCancellationService(factory).cancel(run_id),
    )
    db = factory()
    try:
        run = db.get(DistributionRun, run_id)
        if run.status == "CANCELLED":
            assert db.query(MissionRecord).count() == db.query(Execution).count() == 0
            assert ScheduledDistributionActivationService(factory).scan_once() == []
        else:
            assert run.status == "CREATED" and db.query(MissionRecord).count() == db.query(Execution).count() == 1
            with pytest.raises(ValueError, match="only scheduled"):
                ScheduledDistributionCancellationService(factory).cancel(run_id)
        assert len(outcomes) == 2
    finally:
        db.close()


def test_reschedule_rejects_database_now(factory):
    run_id = _run(factory, datetime.now(timezone.utc) + timedelta(hours=1))
    db = factory()
    try:
        database_now = db.execute(text("SELECT NOW()")).scalar_one()
    finally:
        db.close()
    with pytest.raises(ValueError, match="strictly future"):
        ScheduledDistributionReschedulingService(factory).reschedule(run_id, database_now)


def test_scheduler_vs_reschedule_has_one_coherent_winner(factory):
    run_id = _run(factory, datetime.now(timezone.utc) + timedelta(seconds=1))
    _set_due(factory, run_id)
    _worker(factory)
    new_time = datetime.now(timezone.utc) + timedelta(hours=2)
    outcomes = _race(
        lambda: ScheduledDistributionActivationService(factory).scan_once(),
        lambda: ScheduledDistributionReschedulingService(factory).reschedule(run_id, new_time),
    )
    db = factory()
    try:
        run = db.get(DistributionRun, run_id)
        if run.status == "CREATED":
            assert db.query(MissionRecord).count() == db.query(Execution).count() == 1
            with pytest.raises(ValueError, match="only scheduled"):
                ScheduledDistributionReschedulingService(factory).reschedule(run_id, new_time + timedelta(hours=1))
        else:
            assert run.status == "SCHEDULED" and run.scheduled_for == new_time
            assert db.query(MissionRecord).count() == db.query(Execution).count() == 0
        assert len(outcomes) == 2
    finally:
        db.close()


def test_rescheduled_old_time_is_excluded_then_activates_once(factory):
    run_id = _run(factory, datetime.now(timezone.utc) + timedelta(seconds=1))
    _set_due(factory, run_id)
    new_time = datetime.now(timezone.utc) + timedelta(hours=2)
    ScheduledDistributionReschedulingService(factory).reschedule(run_id, new_time)
    assert ScheduledDistributionActivationService(factory).scan_once() == []
    db = factory()
    try:
        run = db.get(DistributionRun, run_id)
        assert run.status == "SCHEDULED" and run.scheduled_for == new_time
        assert db.query(MissionRecord).count() == db.query(Execution).count() == 0
        run.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    _worker(factory)
    activated = ScheduledDistributionActivationService(factory).scan_once()
    assert len(activated) == 1 and activated[0].spec.idempotency_key == f"distribution:{run_id}"
    assert ScheduledDistributionActivationService(factory).scan_once() == []


def test_cancel_vs_reschedule_has_no_lost_update(factory):
    original_time = datetime.now(timezone.utc) + timedelta(hours=1)
    run_id = _run(factory, original_time)
    new_time = datetime.now(timezone.utc) + timedelta(hours=2)
    outcomes = _race(
        lambda: ScheduledDistributionCancellationService(factory).cancel(run_id),
        lambda: ScheduledDistributionReschedulingService(factory).reschedule(run_id, new_time),
    )
    db = factory()
    try:
        run = db.get(DistributionRun, run_id)
        assert run.status in {"SCHEDULED", "CANCELLED"}
        assert run.scheduled_for in {original_time, new_time}
        assert db.query(MissionRecord).count() == db.query(Execution).count() == 0
        assert len(outcomes) == 2
    finally:
        db.close()
