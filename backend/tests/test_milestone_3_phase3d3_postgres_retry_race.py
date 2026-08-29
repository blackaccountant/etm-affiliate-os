"""Opt-in local PostgreSQL proof that concurrent retry processors claim exactly once."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.executor.executor import TaskExecutor
from app.models.affiliate_program import AffiliateProgram
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.product import Product
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.workforce.status import WorkerStatus


if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip(
        "Requires a local disposable PostgreSQL database; set "
        "ETM_RUN_POSTGRES_INTEGRATION=1 to run.",
        allow_module_level=True,
    )


BASE_POSTGRES_URL = os.getenv("ETM_POSTGRES_INTEGRATION_URL") or "postgresql://postgres:@127.0.0.1:5432/postgres"
base_url = make_url(BASE_POSTGRES_URL)
if base_url.host not in {"localhost", "127.0.0.1", "::1"}:
    raise RuntimeError("Phase 3D3 PostgreSQL proof requires a local loopback database.")


@pytest.fixture(scope="module")
def postgres_session_factory():
    db_name = f"etm_phase3d3_{uuid4().hex}"
    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(str(admin_url), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    database_url = str(base_url.set(database=db_name))
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            MissionRecord.__table__,
            Worker.__table__,
            Execution.__table__,
            Product.__table__,
            AffiliateProgram.__table__,
        ],
    )

    try:
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :db_name AND pid <> pg_backend_pid()"
                ),
                {"db_name": db_name},
            )
            conn.execute(text(f'DROP DATABASE "{db_name}"'))
        admin_engine.dispose()


def seed_retry(session_factory):
    session = session_factory()
    try:
        missions = MissionRepository(session)
        workers = WorkerRepository(session)
        executions = ExecutionRepository(session)

        worker_name = "Product Hunter"
        workers.create(
            name=worker_name,
            worker_type="Test",
            capabilities=["discovery"],
            status=WorkerStatus.ONLINE,
        )

        mission_id = str(uuid4())
        mission = missions.create(
            mission_id=mission_id,
            name="Phase 3D3 retry race",
            objective="Prove exactly one durable retry claim and exactly one workflow execution under PostgreSQL race conditions.",
            workflow_name="phase3d3_retry_race_workflow",
            input_data={"kind": "retry-race", "test": True},
            current_worker_name=worker_name,
        )
        missions.update_status(
            mission.id,
            "RETRY_WAIT",
            current_worker_name=worker_name,
        )

        assert workers.claim(worker_name, mission.id) is True

        execution = executions.create(
            workflow_name="phase3d3_retry_race_workflow",
            status="QUEUED",
            mission_id=mission.id,
            mission_name=mission.name,
            worker_name=worker_name,
            input_data='{"kind": "retry-race", "test": true}',
            retry_count=1,
            max_retries=3,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            failure_type="NETWORK",
            error="previous retryable failure",
        )

        return mission.id, execution.id, worker_name
    finally:
        session.close()


def test_postgres_retry_race_claims_once_and_executes_once(postgres_session_factory):
    mission_id, execution_id, worker_name = seed_retry(postgres_session_factory)

    barrier = threading.Barrier(2)
    workflow_invocations = []
    workflow_lock = threading.Lock()

    class BarrierExecutionService(ExecutionService):
        def get_retry_queue(self, limit=10):
            executions = super().get_retry_queue(limit=limit)
            barrier.wait(timeout=10)
            return executions

    class FakeWorkforce:
        def sync_from_durable(self, durable_worker, mission_name):
            return SimpleNamespace(name=durable_worker.name)

        def release(self, worker_name, success=True):
            return True

    class Engine:
        def run(self, workflow_name, payload):
            with workflow_lock:
                workflow_invocations.append(
                    {
                        "workflow_name": workflow_name,
                        "worker_name": payload.get("worker_name"),
                        "mission_id": payload.get("mission_id"),
                    }
                )
            return {"success": True, "errors": [], "data": {"ok": True}}

    def process_retry():
        session = postgres_session_factory()
        try:
            execution_service = BarrierExecutionService(ExecutionRepository(session))
            scheduler = Scheduler()
            scanner = RetryScanner(execution_service, scheduler)
            executor = TaskExecutor(execution_service=execution_service)
            executor.engine = Engine()
            executor.workforce = FakeWorkforce()

            coordinator = RetryLifecycleCoordinator(
                db=session,
                execution_service=execution_service,
                mission_repository=MissionRepository(session),
                worker_repository=WorkerRepository(session),
                workforce=FakeWorkforce(),
                executor=executor,
            )

            tasks = scanner.scan_once(limit=10)
            if not tasks:
                return False

            result = coordinator.execute(tasks[0])
            return result is not None
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: process_retry(), range(2)))

    inspect = postgres_session_factory()
    try:
        execution = inspect.get(Execution, execution_id)
        mission = inspect.get(MissionRecord, mission_id)
        worker = inspect.get(Worker, worker_name)

        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1
        assert len(workflow_invocations) == 1
        assert workflow_invocations[0]["workflow_name"] == "phase3d3_retry_race_workflow"
        assert workflow_invocations[0]["worker_name"] == worker_name
        assert workflow_invocations[0]["mission_id"] == mission_id

        assert execution.status == "COMPLETED"
        assert execution.result_data is not None
        assert execution.completed_at is not None
        assert execution.completed_at.tzinfo is not None
        assert execution.started_at.tzinfo is not None

        assert mission.status == "COMPLETED"
        assert mission.current_worker_name is None
        assert mission.completed_at is not None
        assert mission.completed_at.tzinfo is not None

        assert worker.status == WorkerStatus.ONLINE.value
        assert worker.current_mission_id is None
        assert worker.missions_completed == 1
        assert worker.missions_failed == 0
        assert worker.success_rate == 100.0

        assert inspect.query(Product).count() == 0
        assert inspect.query(AffiliateProgram).count() == 0
        assert inspect.query(Execution).filter(Execution.mission_id == mission_id).count() == 1
        assert inspect.query(Execution).filter(Execution.status == "QUEUED").count() == 0

        follow_up = RetryScanner(
            ExecutionService(ExecutionRepository(inspect)),
            Scheduler(),
        ).scan_once(limit=10)
        assert follow_up == []
    finally:
        inspect.close()
