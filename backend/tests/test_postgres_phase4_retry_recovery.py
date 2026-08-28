"""Opt-in local PostgreSQL proof that recovered retries execute exactly once."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.executor.executor import TaskExecutor
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus


if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip(
        "Requires a local disposable PostgreSQL database; set "
        "ETM_RUN_POSTGRES_INTEGRATION=1 to run.",
        allow_module_level=True,
    )


POSTGRES_URL = os.environ["DATABASE_URL"]
url = make_url(POSTGRES_URL)
if (url.host, url.port) != ("127.0.0.1", 5432):
    raise RuntimeError("Phase 4 PostgreSQL integration requires loopback PostgreSQL.")
if not url.database or not url.database.startswith("etm_phase4_local_"):
    raise RuntimeError("Phase 4 PostgreSQL integration requires an etm_phase4_local_ database.")


@pytest.fixture
def postgres_session_factory():
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        engine.dispose()


def seed_retry(session_factory):
    session = session_factory()
    try:
        missions = MissionRepository(session)
        workers = WorkerRepository(session)
        executions = ExecutionRepository(session)
        mission = missions.create(
            mission_id="phase4-concurrent-mission",
            name="Recovered Retry",
            objective="Prove exactly-once recovery",
            workflow_name="phase4_concurrent_workflow",
            input_data={"test": True},
            current_worker_name="Product Hunter",
        )
        missions.update_status(mission.id, "RETRY_WAIT", current_worker_name="Product Hunter")
        workers.create(
            name="Product Hunter",
            worker_type="Test",
            capabilities=["recovery"],
            status=WorkerStatus.ONLINE,
        )
        assert workers.claim("Product Hunter", mission.id) is True
        execution = executions.create(
            workflow_name="phase4_concurrent_workflow",
            status="QUEUED",
            mission_id=mission.id,
            mission_name=mission.name,
            worker_name="Product Hunter",
            input_data='{"test": true}',
            retry_count=1,
            max_retries=3,
            next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            failure_type="NETWORK",
            error="previous retryable failure",
        )
        return mission.id, execution.id
    finally:
        session.close()


def test_two_retry_processors_claim_and_execute_once(postgres_session_factory):
    mission_id, execution_id = seed_retry(postgres_session_factory)
    discovery_barrier = threading.Barrier(2)
    counter_lock = threading.Lock()
    workflow_calls = []
    observed = []
    sessions_closed = []

    class BarrierService(ExecutionService):
        def get_retry_queue(self, limit=10):
            executions = super().get_retry_queue(limit=limit)
            discovery_barrier.wait(timeout=10)
            return executions

    class Engine:
        def run(self, workflow_name, payload):
            with counter_lock:
                workflow_calls.append((workflow_name, payload["worker_name"]))
            inspect = postgres_session_factory()
            try:
                observed.append((
                    inspect.get(Execution, execution_id).status,
                    inspect.get(MissionRecord, mission_id).status,
                    inspect.get(Worker, "Product Hunter").status,
                    inspect.get(Worker, "Product Hunter").current_mission_id,
                ))
            finally:
                inspect.close()
            return {"success": True, "workflow": workflow_name, "data": {"test": True}, "errors": []}

    def process_one():
        session = postgres_session_factory()
        try:
            service = BarrierService(ExecutionRepository(session))
            scheduler = Scheduler()
            scanner = RetryScanner(service, scheduler)
            executor = TaskExecutor(execution_service=service)
            executor.workforce = None
            executor.engine = Engine()
            coordinator = RetryLifecycleCoordinator(
                db=session,
                execution_service=service,
                mission_repository=MissionRepository(session),
                worker_repository=WorkerRepository(session),
                workforce=WorkforceManager(),
                executor=executor,
            )
            tasks = scanner.scan_once(limit=1)
            if not tasks:
                return False
            coordinator.execute(tasks[0])
            return True
        finally:
            session.close()
            sessions_closed.append(True)

    with ThreadPoolExecutor(max_workers=2) as processors:
        outcomes = list(processors.map(lambda _: process_one(), range(2)))

    inspect = postgres_session_factory()
    try:
        execution = inspect.get(Execution, execution_id)
        mission = inspect.get(MissionRecord, mission_id)
        worker = inspect.get(Worker, "Product Hunter")
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1
        assert workflow_calls == [("phase4_concurrent_workflow", "Product Hunter")]
        assert observed == [("RETRYING", "RUNNING", "BUSY", mission_id)]
        assert execution.status == "COMPLETED"
        assert mission.status == "COMPLETED"
        assert mission.current_worker_name is None
        assert worker.status == "ONLINE"
        assert worker.current_mission_id is None
        assert worker.missions_completed == 1
        assert worker.missions_failed == 0
        assert inspect.query(Execution).filter(Execution.id == execution_id).count() == 1
    finally:
        inspect.close()

    assert len(sessions_closed) == 2
