"""Guarded PostgreSQL proof for Phase 3R execution recovery."""
import os
import threading
from time import sleep
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.execution_lease import ExecutionLeaseAuthority, ExecutionLeaseHeartbeat
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.executor.executor import TaskExecutor
from app.task_queue.task import Task
from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo
from app.workforce.status import WorkerStatus

_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Phase 3R PostgreSQL proof requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database and "g5" in _url.database.lower() and "test" in _url.database.lower()):
    raise RuntimeError("Phase 3R PostgreSQL proof requires the guarded local G5 test database.")

@pytest.fixture(scope="module")
def engine():
    value = _url.render_as_string(hide_password=False); old = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = value; cfg = Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url", value); command.upgrade(cfg, "head")
    finally: settings.DATABASE_URL = old
    e = create_engine(value, pool_pre_ping=True); yield e; e.dispose()

@pytest.fixture
def factory(engine):
    names = [n for n in inspect(engine).get_table_names() if n != "alembic_version"]
    with engine.begin() as c: c.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{n}\"' for n in names) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)

def seed(factory, expired=False):
    db=factory(); m=MissionRepository(db); w=WorkerRepository(db); e=ExecutionRepository(db)
    mission=m.create(str(uuid4()), "PG recovery", "proof", "pg_recovery", current_worker_name="Recovery Worker"); m.update_status(mission.id,"RUNNING",current_worker_name="Recovery Worker")
    w.create("Recovery Worker","Test",["recovery"],WorkerStatus.ONLINE); assert w.claim("Recovery Worker",mission.id)
    ex=e.create("pg_recovery","RUNNING",mission.id,mission.name,"Recovery Worker",input_data="{}")
    auth=ExecutionLeaseAuthority.fresh(ex.id,1); assert e.acquire_lease(auth,60)
    if expired: db.execute(text("UPDATE executions SET lease_expires_at = NOW() - INTERVAL '2 minutes' WHERE id = :id"),{"id":ex.id}); db.commit()
    mission_id = mission.id
    db.close(); return mission_id,auth

def test_lease_visibility_and_heartbeat(factory, engine):
    _, auth=seed(factory); b=create_engine(_url.render_as_string(hide_password=False)); other=sessionmaker(bind=b)()
    try:
        before=other.get(Execution,auth.execution_id); previous_expiry = before.lease_expires_at
        assert before.lease_owner == auth.lease_owner and before.lease_generation == 1 and previous_expiry > datetime.now(timezone.utc)
        assert ExecutionRepository(other).renew_lease(auth,120); other.expire_all(); renewed = other.get(Execution,auth.execution_id)
        assert renewed.id == auth.execution_id and renewed.lease_owner == auth.lease_owner and renewed.lease_generation == auth.lease_generation
        assert renewed.lease_expires_at.tzinfo is not None and renewed.lease_expires_at > previous_expiry
    finally: other.close(); b.dispose()

@pytest.mark.parametrize("expired,winners",[(False,0),(True,1)])
def test_recovery_race_and_stale_fence(factory, expired, winners):
    mission_id,auth=seed(factory,expired); barrier=threading.Barrier(2); out=[]; lock=threading.Lock()
    def run():
        barrier.wait(); result=RunningExecutionRecoveryService(factory).recover(auth.execution_id)
        with lock: out.append(result)
    ts=[threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in ts]; [t.join(20) for t in ts]; assert all(not t.is_alive() for t in ts); assert sum(x is not None for x in out)==winners
    db=factory(); attempts=db.query(Execution).filter_by(mission_id=mission_id).order_by(Execution.id).all(); mission=db.get(MissionRecord,mission_id); worker=db.get(Worker,"Recovery Worker")
    try:
        if not expired: assert len(attempts)==1 and attempts[0].status=="RUNNING" and worker.current_mission_id==mission_id; return
        first,second=attempts; assert first.status=="ABANDONED" and len(attempts)==2 and second.lease_generation==first.lease_generation+1 and second.lease_owner != first.lease_owner and mission.status=="RUNNING" and worker.status=="BUSY"
        repo=ExecutionRepository(db)
        for fn in (lambda:repo.complete_owned(auth),lambda:repo.fail_owned(auth,error="stale"),lambda:repo.schedule_retry_owned(auth,retry_count=1,max_retries=3,next_retry_at=datetime.now(timezone.utc))):
            with pytest.raises(ExecutionLeaseLostError): fn()
    finally: db.close()

def test_recovered_replacement_dispatches_exactly_once(factory):
    mission_id, auth = seed(factory, True)
    recovered = RunningExecutionRecoveryService(factory).recover(auth.execution_id)
    assert recovered is not None
    calls = []
    class Engine:
        def run(self, workflow_name, payload):
            calls.append((workflow_name, payload.get("recovered_execution_id")))
            return {"success": True, "errors": []}
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Recovery Worker", "Test", capabilities=["recovery"], status=WorkerStatus.ONLINE))
    manager = MissionManager(workforce=workforce, session_factory=factory)
    manager.executor.engine = Engine()
    result = manager.resume_recovered_mission(recovered)
    assert result.success is True
    assert RunningExecutionRecoveryService(factory).recover(auth.execution_id) is None
    db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=mission_id).order_by(Execution.id).all()
        mission = db.get(MissionRecord, mission_id); worker = db.get(Worker, "Recovery Worker")
        assert len(attempts) == 2 and attempts[0].status == "ABANDONED"
        assert attempts[1].id == recovered.replacement_execution_id and attempts[1].status == "COMPLETED"
        assert mission.status == "COMPLETED" and worker.status == "ONLINE" and worker.current_mission_id is None
        assert calls == [("pg_recovery", auth.execution_id)]
    finally: db.close()

def test_heartbeat_protected_execution_cannot_be_recovered(factory):
    mission_id, auth = seed(factory)
    started, release, outcome = threading.Event(), threading.Event(), []
    class BlockingEngine:
        def __init__(self): self.calls = 0
        def run(self, workflow_name, payload):
            self.calls += 1; started.set(); assert release.wait(10); return {"success": True, "errors": []}
    executor = TaskExecutor(); engine = BlockingEngine(); executor.engine = engine
    task = Task("pg_recovery", {}); task.assign_worker(type("WorkerInfo", (), {"name":"Recovery Worker"})())
    runner = ExecutionAttemptRunner(factory, executor, lease_seconds=120, heartbeat_seconds=.05)
    thread = threading.Thread(target=lambda: outcome.append(runner.execute(execution_id=auth.execution_id, mission_id=mission_id, mission_name="PG recovery", worker_name="Recovery Worker", task=task, authority=auth)))
    thread.start(); assert started.wait(5)
    probe=factory(); first=probe.get(Execution,auth.execution_id); expiry_1=first.lease_expires_at; assert first.lease_owner and first.lease_generation == 1 and expiry_1 > datetime.now(timezone.utc); probe.close()
    sleep(.12)
    probe=factory(); current=probe.get(Execution,auth.execution_id); expiry_2=current.lease_expires_at; mission=probe.get(MissionRecord,mission_id); worker=probe.get(Worker,"Recovery Worker")
    try:
        assert expiry_2 > expiry_1 and mission.status == "RUNNING" and worker.status == "BUSY"
        assert RunningExecutionRecoveryService(factory, lease_seconds=1).recover(auth.execution_id) is None
        assert probe.query(Execution).filter_by(mission_id=mission_id).count() == 1
    finally: probe.close()
    release.set(); thread.join(10); assert not thread.is_alive() and engine.calls == 1
    probe=factory()
    try:
        assert probe.get(Execution,auth.execution_id).status == "COMPLETED"
        assert probe.get(MissionRecord,mission_id).status == "COMPLETED"
        final_worker=probe.get(Worker,"Recovery Worker"); assert final_worker.status == "ONLINE" and final_worker.current_mission_id is None
    finally: probe.close()

def test_fresh_engine_runtime_restart_recovers_and_dispatches(engine):
    """Recovery B owns no objects from simulated-crashed runtime A."""
    engine_a = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    factory_a = sessionmaker(bind=engine_a, autoflush=False, autocommit=False)
    # The module-level fixture has already bootstrapped the guarded schema.
    with engine_a.begin() as connection:
        names = [n for n in inspect(engine_a).get_table_names() if n != "alembic_version"]
        connection.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{n}\"' for n in names) + " RESTART IDENTITY CASCADE"))
    runtime_a = MissionManager(workforce=WorkforceManager(), session_factory=factory_a)
    executor_a = TaskExecutor(); runner_a = ExecutionAttemptRunner(factory_a, executor_a)
    recovery_a = RunningExecutionRecoveryService(factory_a)
    _ = (runtime_a, runner_a, recovery_a)  # Explicitly construct Runtime A components.
    mission_id, old_authority = seed(factory_a)
    session_a = factory_a()
    try:
        pid_a = session_a.execute(text("SELECT pg_backend_pid()")).scalar_one()
        e1 = session_a.get(Execution, old_authority.execution_id)
        e1_generation, e1_owner = e1.lease_generation, e1.lease_owner
    finally:
        session_a.close()
    engine_a.dispose()

    engine_b = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    factory_b = sessionmaker(bind=engine_b, autoflush=False, autocommit=False)
    try:
        expiry = factory_b()
        try:
            expiry.execute(text("UPDATE executions SET lease_expires_at = NOW() - INTERVAL '2 minutes' WHERE id = :id"), {"id": old_authority.execution_id})
            expiry.commit()
        finally:
            expiry.close()
        runtime_b_workforce = WorkforceManager()
        runtime_b_workforce.register(WorkerInfo("Recovery Worker", "Test", capabilities=["recovery"], status=WorkerStatus.ONLINE))
        runtime_b = MissionManager(workforce=runtime_b_workforce, session_factory=factory_b)
        calls = []
        class RestartEngine:
            def run(self, workflow_name, payload):
                calls.append((workflow_name, payload.get("recovered_execution_id")))
                return {"success": True, "errors": []}
        runtime_b.executor.engine = RestartEngine()
        executor_b = runtime_b.executor; runner_b = ExecutionAttemptRunner(factory_b, executor_b)
        recovery_b = RunningExecutionRecoveryService(factory_b)
        _ = (executor_b, runner_b)
        pid_session = factory_b()
        try:
            pid_b = pid_session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        finally:
            pid_session.close()
        assert pid_b != pid_a
        recovered = recovery_b.recover(old_authority.execution_id)
        assert recovered is not None
        result = runtime_b.resume_recovered_mission(recovered)
        assert result.success is True and calls == [("pg_recovery", old_authority.execution_id)]
        db = factory_b()
        try:
            attempts = db.query(Execution).filter_by(mission_id=mission_id).order_by(Execution.id).all()
            mission = db.get(MissionRecord, mission_id); worker = db.get(Worker, "Recovery Worker")
            assert len(attempts) == 2 and attempts[0].status == "ABANDONED"
            assert attempts[0].lease_generation == e1_generation and attempts[0].lease_owner == e1_owner
            assert attempts[1].lease_generation == e1_generation + 1 and attempts[1].lease_owner != e1_owner
            assert attempts[1].status == "COMPLETED" and mission.status == "COMPLETED"
            assert worker.status == "ONLINE" and worker.current_mission_id is None
            repository = ExecutionRepository(db)
            for operation in (
                lambda: repository.complete_owned(old_authority),
                lambda: repository.fail_owned(old_authority, error="stale"),
                lambda: repository.schedule_retry_owned(old_authority, retry_count=1, max_retries=3, next_retry_at=datetime.now(timezone.utc)),
            ):
                with pytest.raises(ExecutionLeaseLostError): operation()
        finally:
            db.close()
    finally:
        engine_b.dispose()
