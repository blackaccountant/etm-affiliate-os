"""Guarded PostgreSQL proofs for queued distribution retry cancellation."""

from datetime import datetime, timedelta, timezone
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.distribution.mission_contracts import distribution_mission_idempotency_key
from app.models.discovery import DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.distribution_run_service import DistributionRunService
from app.services.queued_retry_cancellation_service import QueuedRetryCancellationService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request
from tests.test_milestone_5_phase5e2e_postgresql_operation_races import _lineage


_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("Phase 5F.2B requires guarded local G5.")


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


def _queued_retry(factory):
    db = factory()
    try:
        _lineage(db)
        run = DistributionRunService(db).create(request(scheduled_for=None))
        run.status = "RETRY_WAIT"
        mission = MissionRepository(db).create("retry-mission", "Distribution", "retry", "distribution_publish", status="RETRY_WAIT", input_data={"distribution_run_id": run.id}, idempotency_key=distribution_mission_idempotency_key(run.id), current_worker_name="Worker")
        WorkerRepository(db).create("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)
        assert WorkerRepository(db).claim("Worker", mission.id)
        execution = ExecutionRepository(db).create("distribution_publish", "QUEUED", mission.id, mission.name, "Worker", input_data='{"distribution_run_id": "%s"}' % run.id, retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        db.commit()
        return run.id, mission.id, execution.id
    finally:
        db.close()


def _race(*actions):
    barrier = threading.Barrier(len(actions)); outcomes = []
    def invoke(action):
        barrier.wait()
        try: outcomes.append(("ok", action()))
        except ValueError: outcomes.append(("rejected", None))
    threads = [threading.Thread(target=invoke, args=(action,)) for action in actions]
    for thread in threads: thread.start()
    for thread in threads: thread.join(20)
    assert all(not thread.is_alive() for thread in threads)
    return outcomes


def _claim(factory, execution_id):
    session = factory()
    try:
        return ExecutionRepository(session).claim_due_retry(execution_id)
    finally:
        session.close()


def test_clean_cancel_is_terminal_idempotent_and_not_recoverable(factory):
    run_id, mission_id, execution_id = _queued_retry(factory)
    service = QueuedRetryCancellationService(factory)
    assert service.cancel(run_id).status == service.cancel(run_id).status == "CANCELLED"
    db = factory()
    try:
        execution = db.get(Execution, execution_id)
        assert (db.get(DistributionRun, run_id).status, db.get(MissionRecord, mission_id).status, execution.status) == ("CANCELLED", "FAILED", "FAILED")
        assert execution.next_retry_at is execution.lease_owner is execution.lease_expires_at is None
        assert db.get(Worker, "Worker").status == "ONLINE"
    finally: db.close()
    assert _claim(factory, execution_id) is None
    assert RunningExecutionRecoveryService(factory).recover(execution_id) is None


def test_concurrent_cancels_are_idempotent(factory):
    run_id, mission_id, execution_id = _queued_retry(factory)
    assert len(_race(lambda: QueuedRetryCancellationService(factory).cancel(run_id), lambda: QueuedRetryCancellationService(factory).cancel(run_id))) == 2
    db = factory()
    try:
        assert (db.get(DistributionRun, run_id).status, db.get(MissionRecord, mission_id).status, db.get(Execution, execution_id).status) == ("CANCELLED", "FAILED", "FAILED")
    finally: db.close()


def test_cancel_vs_claim_has_one_coherent_winner(factory):
    run_id, mission_id, execution_id = _queued_retry(factory)
    outcomes = _race(lambda: QueuedRetryCancellationService(factory).cancel(run_id), lambda: _claim(factory, execution_id))
    db = factory()
    try:
        execution = db.get(Execution, execution_id)
        if execution.status == "FAILED":
            assert db.get(DistributionRun, run_id).status == "CANCELLED" and db.get(MissionRecord, mission_id).status == "FAILED"
        else:
            assert execution.status == "RETRYING" and db.get(MissionRecord, mission_id).status == "RUNNING"
            with pytest.raises(ValueError): QueuedRetryCancellationService(factory).cancel(run_id)
        assert len(outcomes) == 2
    finally: db.close()


def test_corrupt_queued_retry_rejects_without_partial_mutation(factory):
    run_id, mission_id, execution_id = _queued_retry(factory)
    db = factory(); db.get(MissionRecord, mission_id).status = "COMPLETED"; db.commit(); db.close()
    with pytest.raises(ValueError): QueuedRetryCancellationService(factory).cancel(run_id)
    db = factory()
    try: assert db.get(DistributionRun, run_id).status == "RETRY_WAIT" and db.get(Execution, execution_id).status == "QUEUED"
    finally: db.close()
