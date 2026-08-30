"""Guarded PostgreSQL proofs for durable due scheduled activation."""
from datetime import datetime, timedelta, timezone
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.distribution_run import DistributionRun
from app.models.discovery import DiscoveryRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.worker_repository import WorkerRepository
from app.services.distribution_run_service import DistributionRunService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.scheduled_distribution_activation_service import ScheduledDistributionActivationService
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request
from tests.test_milestone_5_phase5e2e_postgresql_operation_races import _lineage

_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw: pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("Phase 5F.1 requires guarded local G5.")

@pytest.fixture(scope="module")
def engine():
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    with engine.connect() as c: assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "fa1b2c3d4e5f"
    yield engine; engine.dispose()

@pytest.fixture
def factory(engine):
    with engine.begin() as c:
        names=[n for n in inspect(engine).get_table_names() if n != "alembic_version"]
        c.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{n}\"' for n in names) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def _run(factory, when, destination="blog"):
    db=factory()
    if db.get(DiscoveryRun, "discovery") is None:
        _lineage(db)
    run=DistributionRunService(db).create(request(destination=destination, scheduled_for=when)); db.commit(); db.close(); return run.id
def _worker(factory):
    db=factory(); WorkerRepository(db).create("Worker","Test",["content_distribution"],WorkerStatus.ONLINE); db.close()

def _due(factory, destination="blog", seconds_ago=60):
    run_id = _run(factory, datetime.now(timezone.utc) + timedelta(seconds=1), destination)
    db = factory()
    db.get(DistributionRun, run_id).scheduled_for = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.commit(); db.close()
    return run_id

def _release(factory, operation):
    db = factory()
    assert WorkerRepository(db).release(operation.worker_name, operation.mission_id, success=True)
    db.close()

def test_two_schedulers_create_one_due_operation(factory):
    run_id=_run(factory,datetime.now(timezone.utc)+timedelta(seconds=1)); db=factory(); db.get(DistributionRun,run_id).scheduled_for=datetime.now(timezone.utc)-timedelta(minutes=1); db.commit(); db.close(); _worker(factory)
    barrier=threading.Barrier(2); outcomes=[]
    def scan(): barrier.wait(); outcomes.append(ScheduledDistributionActivationService(factory).scan_once())
    threads=[threading.Thread(target=scan) for _ in range(2)]; [t.start() for t in threads]; [t.join(20) for t in threads]; assert all(not t.is_alive() for t in threads)
    db=factory(); mission=db.query(MissionRecord).filter_by(idempotency_key=f"distribution:{run_id}").one(); assert db.get(DistributionRun,run_id).status=="CREATED" and db.query(Execution).filter_by(mission_id=mission.id).count()==1; db.close()

def test_no_worker_and_future_rows_remain_scheduled(factory):
    due=_run(factory,datetime.now(timezone.utc)+timedelta(seconds=1),"due"); future=_run(factory,datetime.now(timezone.utc)+timedelta(hours=1),"future")
    db=factory(); db.get(DistributionRun,due).scheduled_for=datetime.now(timezone.utc)-timedelta(minutes=1); db.commit(); db.close()
    assert ScheduledDistributionActivationService(factory).scan_once()==[]
    db=factory(); assert db.get(DistributionRun,due).status==db.get(DistributionRun,future).status=="SCHEDULED" and db.query(MissionRecord).count()==db.query(Execution).count()==0; db.close()

def test_overdue_restart_activation_preserves_business_identity_and_payload(factory):
    run_id = _due(factory, "restart")
    _worker(factory)
    # A newly constructed scanner proves the due predicate is durable DB state, not timer state.
    activated = ScheduledDistributionActivationService(factory).scan_once()
    assert len(activated) == 1
    db = factory()
    run = db.get(DistributionRun, run_id)
    mission = db.query(MissionRecord).filter_by(idempotency_key=f"distribution:{run_id}").one()
    assert run.status == "CREATED" and db.query(DistributionRun).filter_by(id=run_id).count() == 1
    assert db.query(MissionRecord).count() == db.query(Execution).count() == 1
    assert mission.input_data == '{"distribution_run_id": "%s"}' % run_id
    db.close()

def test_due_selection_is_deterministic_and_repeat_scan_is_idempotent(factory):
    first = _due(factory, "first", seconds_ago=180)
    tied_first = _due(factory, "tied-first", seconds_ago=120)
    tied_second = _due(factory, "tied-second", seconds_ago=120)
    db = factory()
    tie_time = datetime.now(timezone.utc) - timedelta(minutes=2)
    db.get(DistributionRun, tied_first).scheduled_for = tie_time
    db.get(DistributionRun, tied_second).scheduled_for = tie_time
    db.commit(); db.close()
    _worker(factory)
    scanner = ScheduledDistributionActivationService(factory)
    first_operation = scanner.scan_once(1)[0]
    assert first_operation.spec.idempotency_key == f"distribution:{first}"
    _release(factory, first_operation)
    tied_operation = scanner.scan_once(1)[0]
    assert tied_operation.spec.idempotency_key == f"distribution:{min(tied_first, tied_second)}"
    _release(factory, tied_operation)
    final_operation = scanner.scan_once(1)[0]
    assert final_operation.spec.idempotency_key == f"distribution:{max(tied_first, tied_second)}"
    _release(factory, final_operation)
    assert scanner.scan_once() == []
    db = factory()
    assert db.query(MissionRecord).count() == db.query(Execution).count() == 3
    assert db.query(MissionRecord).filter_by(idempotency_key=f"distribution:{first}").count() == 1
    db.close()

def test_undispatched_due_operation_recovers_and_capacity_leaves_one_scheduled(factory):
    first=_run(factory,datetime.now(timezone.utc)+timedelta(seconds=1),"first"); second=_run(factory,datetime.now(timezone.utc)+timedelta(seconds=2),"second")
    db=factory(); db.get(DistributionRun,first).scheduled_for=datetime.now(timezone.utc)-timedelta(minutes=2); db.get(DistributionRun,second).scheduled_for=datetime.now(timezone.utc)-timedelta(minutes=1); db.commit(); db.close(); _worker(factory)
    activated=ScheduledDistributionActivationService(factory).scan_once(2); assert len(activated)==1
    operation=activated[0]; db=factory(); db.execute(text("UPDATE executions SET lease_expires_at=NOW()-INTERVAL '1 minute' WHERE id=:id"),{"id":operation.execution_id}); db.commit(); db.close()
    recovered=RunningExecutionRecoveryService(factory).recover(operation.execution_id); db=factory(); assert recovered and db.get(DistributionRun,second).status=="SCHEDULED" and db.query(Execution).filter_by(mission_id=operation.mission_id).count()==2; db.close()
