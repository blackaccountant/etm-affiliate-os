"""Guarded real-PostgreSQL qualification for generic retry authority (M9C2R1)."""

from datetime import datetime, timedelta, timezone
import os
import threading
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.execution import Execution
from app.core.config import settings
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.execution_service import ExecutionService
from app.task_queue.task import Task
from app.workforce.status import WorkerStatus


RAW_URL = os.getenv("ETM_G5_DATABASE_URL")
if not RAW_URL:
    pytest.skip("M9C2R1 requires explicit ETM_G5_DATABASE_URL", allow_module_level=True)
URL = make_url(RAW_URL)
if not (URL.drivername.startswith("postgresql") and URL.host == "127.0.0.1"
        and URL.port == 5432 and URL.database == "etm_g5_m9c2r1_qualification"):
    raise RuntimeError("M9C2R1 permits only the guarded etm_g5_m9c2r1_qualification database")


@pytest.fixture(scope="module")
def engine():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", URL.render_as_string(hide_password=False))
    previous_url = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = URL.render_as_string(hide_password=False)
        command.upgrade(config, "head")
    finally:
        settings.DATABASE_URL = previous_url
    candidate = create_engine(URL.render_as_string(hide_password=False), pool_pre_ping=True)
    try:
        with candidate.connect() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one() == URL.database
        yield candidate
    finally:
        candidate.dispose()


@pytest.fixture
def factory(engine):
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{name}\"' for name in tables) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def seed(factory, *, due=True, retries=1, max_retries=3, mission=True, mission_status="RETRY_WAIT",
         worker=True, worker_status="BUSY", ownership=True):
    db = factory()
    try:
        suffix = uuid4().hex
        mission_id, worker_name = f"m9c2r1-mission-{suffix}", f"M9C2R1 Worker {suffix}"
        if mission:
            MissionRepository(db).create(mission_id, "Retry", "qualify", "retry_workflow",
                status=mission_status, current_worker_name=worker_name if ownership else "Other")
        if worker:
            WorkerRepository(db).create(worker_name, "Test", ["retry"], WorkerStatus.ONLINE)
            row = db.get(Worker, worker_name)
            row.status = worker_status
            row.current_mission_id = mission_id if ownership else "other-mission"
        execution = ExecutionRepository(db).create("retry_workflow", "QUEUED", mission_id,
            "Retry", worker_name, input_data='{"safe": true}', retry_count=retries,
            max_retries=max_retries,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1) if due else datetime.now(timezone.utc) + timedelta(hours=1))
        db.commit()
        return execution.id, mission_id, worker_name
    finally:
        db.close()


def snapshot(factory, execution_id, mission_id, worker_name):
    db = factory()
    try:
        e, m, w = db.get(Execution, execution_id), db.get(MissionRecord, mission_id), db.get(Worker, worker_name)
        return (None if e is None else (e.status, e.retry_count, e.next_retry_at, e.lease_owner, e.lease_generation, e.lease_expires_at, e.error),
                None if m is None else (m.status, m.current_worker_name),
                None if w is None else (w.status, w.current_mission_id))
    finally:
        db.close()


def assert_json_safe_without_authority(value):
    """Prove scanner payloads contain durable data, never lease authority."""
    assert not isinstance(value, ExecutionLeaseAuthority)
    if isinstance(value, dict):
        forbidden = {"retry_authority", "execution_authority", "lease_owner",
                     "lease_generation", "lease_expires_at"}
        assert not (set(value) & forbidden)
        for nested in value.values():
            assert_json_safe_without_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            assert_json_safe_without_authority(nested)


def assert_retrying_snapshot(state, authority, mission_id, worker_name):
    execution, mission, worker = state
    assert execution[0] == "RETRYING"
    assert execution[3] == authority.lease_owner
    assert execution[4] == authority.lease_generation
    assert execution[5] > datetime.now(timezone.utc)
    assert execution[2] is None
    assert mission == ("RUNNING", worker_name)
    assert worker == ("BUSY", mission_id)


def claim(factory, execution_id):
    db = factory()
    try:
        return ExecutionRepository(db).claim_due_retry(execution_id)
    finally:
        db.close()


def test_q01_q09_valid_claim_and_q14_verify(factory):
    execution_id, mission_id, worker_name = seed(factory)
    before = snapshot(factory, execution_id, mission_id, worker_name)
    claimed = claim(factory, execution_id)
    assert claimed is not None and claimed.status == "RETRYING"
    authority = claimed.retry_authority
    after = snapshot(factory, execution_id, mission_id, worker_name)
    assert after[0][3] == authority.lease_owner and after[0][4] == before[0][4] + 1
    assert after[0][5] > datetime.now(timezone.utc) and after[1] == ("RUNNING", worker_name)
    assert after[2] == ("BUSY", mission_id)
    db = factory()
    try:
        assert ExecutionRepository(db).verify_active_authority(authority).id == execution_id
    finally:
        db.close()


@pytest.mark.parametrize("label,kwargs", [
    ("Q02", {"due": False}), ("Q03", {"retries": 3, "max_retries": 3}),
    ("Q04", {"mission": False}), ("Q05", {"mission_status": "RUNNING"}),
    ("Q06", {"worker": False}), ("Q07", {"worker_status": "ONLINE"}),
    ("Q08", {"ownership": False}),
])
def test_q02_to_q08_rejections_are_atomic(factory, label, kwargs):
    execution_id, mission_id, worker_name = seed(factory, **kwargs)
    before = snapshot(factory, execution_id, mission_id, worker_name)
    assert claim(factory, execution_id) is None, label
    assert snapshot(factory, execution_id, mission_id, worker_name) == before, label


def test_q10_two_postgresql_claimers(factory):
    execution_id, mission_id, worker_name = seed(factory)
    original = snapshot(factory, execution_id, mission_id, worker_name)
    barrier, results, lock = threading.Barrier(2), [], threading.Lock()
    def contender():
        db = factory()
        try:
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            barrier.wait(timeout=10)
            value = ExecutionRepository(db).claim_due_retry(execution_id)
            with lock: results.append((pid, value.retry_authority if value else None))
        finally: db.close()
    threads = [threading.Thread(target=contender) for _ in range(2)]
    [thread.start() for thread in threads]; [thread.join(20) for thread in threads]
    assert all(not thread.is_alive() for thread in threads)
    assert len({pid for pid, _ in results}) == 2 and sum(item[1] is not None for item in results) == 1
    print(f"Q10 PostgreSQL backend PIDs: {sorted(pid for pid, _ in results)}")
    winner = next(authority for _, authority in results if authority)
    persisted = snapshot(factory, execution_id, mission_id, worker_name)
    assert_retrying_snapshot(persisted, winner, mission_id, worker_name)
    assert persisted[0][4] == original[0][4] + 1
    assert persisted[0][3] is not None


def test_q11_restore_and_q16_scanner_threads_exact_authority(factory):
    execution_id, mission_id, worker_name = seed(factory)
    claimed = claim(factory, execution_id)
    db = factory()
    try:
        assert ExecutionRepository(db).restore_due_retry_claim(execution_id, claimed.retry_authority, "schedule failed")
    finally: db.close()
    state = snapshot(factory, execution_id, mission_id, worker_name)
    assert state[0][0] == "QUEUED" and state[0][3] is state[0][5] is None and state[0][4] == 1
    assert state[1] == ("RETRY_WAIT", worker_name) and state[2] == ("BUSY", mission_id)

    class Service:
        def __init__(self): self.restored = None
        def get_retry_queue(self, limit): return [type("E", (), {"id": execution_id, "workflow_name": "retry_workflow"})()]
        def claim_due_retry(self, _): return type("E", (), {"id": execution_id, "workflow_name": "retry_workflow", "mission_id": mission_id, "worker_name": worker_name, "retry_count": 1, "max_retries": 3, "failure_type": None, "input_data": '{"safe": true}', "retry_authority": claimed.retry_authority})()
        def restore_due_retry_claim(self, execution_id, authority, error): self.restored = (execution_id, authority, error); return True
    class CapturingScheduler:
        def __init__(self): self.kwargs = None; self.task = None
        def schedule(self, **kwargs):
            self.kwargs = kwargs
            self.task = Task(kwargs["workflow_name"], kwargs["payload"])
            return self.task
    service = Service(); scheduler = CapturingScheduler()
    tasks = RetryScanner(service, scheduler).scan_once()
    assert tasks == [scheduler.task]
    payload = scheduler.kwargs["payload"]
    assert_json_safe_without_authority(payload)
    assert scheduler.task.execution_authority is claimed.retry_authority
    assert "retry_authority" not in payload and "execution_authority" not in payload
    assert snapshot(factory, execution_id, mission_id, worker_name)[0][0] == "QUEUED"
    db = factory()
    try:
        assert db.get(Execution, execution_id).input_data == '{"safe": true}'
    finally:
        db.close()


def test_q12_restore_rejections_write_nothing(factory):
    for kind in ("id", "owner", "generation", "expired", "mission", "worker"):
        execution_id, mission_id, worker_name = seed(factory)
        claimed = claim(factory, execution_id); authority = claimed.retry_authority
        db = factory()
        try:
            if kind == "expired": db.get(Execution, execution_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            elif kind == "mission": db.get(MissionRecord, mission_id).status = "RETRY_WAIT"
            elif kind == "worker": db.get(Worker, worker_name).status = "ONLINE"
            db.commit()
        finally: db.close()
        before = snapshot(factory, execution_id, mission_id, worker_name)
        bad = authority
        call_id = execution_id
        if kind == "id": call_id += 1
        if kind == "owner": bad = ExecutionLeaseAuthority(execution_id, "wrong", authority.lease_generation)
        if kind == "generation": bad = ExecutionLeaseAuthority(execution_id, authority.lease_owner, authority.lease_generation + 1)
        db = factory()
        try: assert not ExecutionRepository(db).restore_due_retry_claim(call_id, bad, "no")
        finally: db.close()
        assert snapshot(factory, execution_id, mission_id, worker_name) == before, kind


def test_q13_restore_failure_rolls_back(factory, monkeypatch):
    execution_id, mission_id, worker_name = seed(factory); claimed = claim(factory, execution_id)
    db = factory(); repo = ExecutionRepository(db); before = snapshot(factory, execution_id, mission_id, worker_name)
    def fail_commit_after_flush():
        db.flush()
        db.rollback()
        raise RuntimeError("injected failure after restore SQL flush")
    monkeypatch.setattr(db, "commit", fail_commit_after_flush)
    with pytest.raises(RuntimeError): repo.restore_due_retry_claim(execution_id, claimed.retry_authority, "boom")
    db.close()
    assert snapshot(factory, execution_id, mission_id, worker_name) == before

    # Claim has already assigned Execution/Mission attributes when commit is
    # injected to fail; rollback must likewise leave all three rows untouched.
    execution_id, mission_id, worker_name = seed(factory)
    db = factory(); repo = ExecutionRepository(db); before = snapshot(factory, execution_id, mission_id, worker_name)
    def fail_claim_commit_after_flush():
        db.flush()
        db.rollback()
        raise RuntimeError("injected failure after claim SQL flush")
    monkeypatch.setattr(db, "commit", fail_claim_commit_after_flush)
    with pytest.raises(RuntimeError): repo.claim_due_retry(execution_id)
    db.close()
    assert snapshot(factory, execution_id, mission_id, worker_name) == before


def test_q15_expired_and_superseded_authority_fail_closed(factory):
    execution_id, mission_id, worker_name = seed(factory); claimed = claim(factory, execution_id); authority = claimed.retry_authority
    db = factory()
    try:
        db.get(Execution, execution_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
        repo = ExecutionRepository(db)
        with pytest.raises(ExecutionLeaseLostError): repo.verify_active_authority(authority)
        for fn in (lambda: repo.complete_owned(authority), lambda: repo.fail_owned(authority, error="x"), lambda: repo.schedule_retry_owned(authority, retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc))):
            with pytest.raises(ExecutionLeaseLostError): fn()
        assert not repo.renew_lease(authority, 90)
        assert not repo.restore_due_retry_claim(execution_id, authority, "x")
    finally: db.close()
    assert snapshot(factory, execution_id, mission_id, worker_name)[0][0] == "RETRYING"

    execution_id, mission_id, worker_name = seed(factory); claimed = claim(factory, execution_id); stale = claimed.retry_authority
    db = factory()
    try:
        current = db.get(Execution, execution_id)
        current.lease_owner, current.lease_generation = "superseding-owner", stale.lease_generation + 1
        current.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1); db.commit()
        repo = ExecutionRepository(db)
        with pytest.raises(ExecutionLeaseLostError): repo.verify_active_authority(stale)
        for fn in (lambda: repo.complete_owned(stale), lambda: repo.fail_owned(stale, error="x"), lambda: repo.schedule_retry_owned(stale, retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc))):
            with pytest.raises(ExecutionLeaseLostError): fn()
        assert not repo.renew_lease(stale, 90)
        assert not repo.restore_due_retry_claim(execution_id, stale, "x")
    finally: db.close()


def test_q17_q18_lifecycle_fails_closed_or_restores_owned_claim(factory):
    execution_id, mission_id, worker_name = seed(factory); claimed = claim(factory, execution_id)
    class Workforce:
        def sync_from_durable(self, *_): raise RuntimeError("prep failed")
    class Executor: pass
    db = factory()
    try:
        service = ExecutionService(ExecutionRepository(db))
        coordinator = RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), Workforce(), Executor(), session_factory=factory)
        task = Task("retry_workflow", {"execution_id": execution_id, "mission_id": mission_id, "worker_name": worker_name})
        before = snapshot(factory, execution_id, mission_id, worker_name)
        assert coordinator.execute(task) is None  # missing authority: no mutation
        assert snapshot(factory, execution_id, mission_id, worker_name) == before
        task.execution_authority = ExecutionLeaseAuthority(execution_id, "wrong", claimed.retry_authority.lease_generation)
        assert coordinator.execute(task) is None  # stale/wrong authority: no mutation
        assert snapshot(factory, execution_id, mission_id, worker_name) == before
        task.execution_authority = claimed.retry_authority
        with pytest.raises(RuntimeError, match="prep failed"): coordinator.execute(task)
    finally: db.close()
    after = snapshot(factory, execution_id, mission_id, worker_name)
    assert after[0][0] == "QUEUED" and after[0][1] == 1 and after[1] == ("RETRY_WAIT", worker_name)
    assert after[2] == ("BUSY", mission_id)


def test_q17_stale_and_expired_coordinator_authority_write_nothing(factory):
    class NeverRunWorkforce:
        def sync_from_durable(self, *_):
            raise AssertionError("workflow preparation must not run without active authority")

    class GuardedService(ExecutionService):
        def fail(self, *args, **kwargs):
            raise AssertionError("legacy unfenced fail must not be called")

        def schedule_retry(self, *args, **kwargs):
            raise AssertionError("legacy unfenced schedule_retry must not be called")

    def coordinator_for(db):
        return RetryLifecycleCoordinator(
            db, GuardedService(ExecutionRepository(db)), MissionRepository(db),
            WorkerRepository(db), NeverRunWorkforce(), object(), session_factory=factory,
        )

    execution_id, mission_id, worker_name = seed(factory)
    stale = claim(factory, execution_id).retry_authority
    db = factory()
    try:
        row = db.get(Execution, execution_id)
        current = ExecutionLeaseAuthority(execution_id, "successor", stale.lease_generation + 1)
        row.lease_owner = current.lease_owner
        row.lease_generation = current.lease_generation
        row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        db.commit()
        before = snapshot(factory, execution_id, mission_id, worker_name)
        task = Task("retry_workflow", {"execution_id": execution_id, "mission_id": mission_id, "worker_name": worker_name})
        task.execution_authority = stale
        assert coordinator_for(db).execute(task) is None
    finally:
        db.close()
    assert snapshot(factory, execution_id, mission_id, worker_name) == before

    execution_id, mission_id, worker_name = seed(factory)
    authority = claim(factory, execution_id).retry_authority
    db = factory()
    try:
        db.get(Execution, execution_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        before = snapshot(factory, execution_id, mission_id, worker_name)
        task = Task("retry_workflow", {"execution_id": execution_id, "mission_id": mission_id, "worker_name": worker_name})
        task.execution_authority = authority
        assert coordinator_for(db).execute(task) is None
    finally:
        db.close()
    assert snapshot(factory, execution_id, mission_id, worker_name) == before
