"""Explicitly gated PostgreSQL race/restart acceptance suite for Phase 4G5."""

import os
import threading

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.content_evaluation import ContentEvaluation
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.execution_service import ExecutionService
from app.executor.executor import TaskExecutor
from app.workflows.content.content_generation_workflow import ContentGenerationWorkflow
from app.workflows.content.content_repurposing_workflow import ContentRepurposingWorkflow
from app.content_intelligence.generation_service import ContentGenerationService
from app.content_intelligence.repurposing_service import ContentRepurposingService
from tests.test_milestone_4_phase4g3_content_generation_retry_resume import Provider as GenerationProvider, Factory as GenerationFactory, ready_run as generation_ready, launch as generation_launch, timeout as generation_timeout, success as generation_success, Engine as GenerationEngine
from tests.test_milestone_4_phase4g4_content_repurposing_mission import Provider as RepurposingProvider, Factory as RepurposingFactory, ready_run as repurposing_ready, launch as repurposing_launch, failure as repurposing_failure, success as repurposing_success
from app.content_intelligence.generation_contracts import ProviderFailureCategory
from app.workforce.manager import WorkforceManager


RAW_G5_URL = os.getenv("ETM_G5_DATABASE_URL")
if not RAW_G5_URL:
    pytest.skip(
        "Phase 4G5 requires explicit ETM_G5_DATABASE_URL for a disposable PostgreSQL test database.",
        allow_module_level=True,
    )


G5_URL = make_url(RAW_G5_URL)
_FORBIDDEN_DATABASES = {"postgres", "etm_affiliate_os", "production", "prod"}
if not G5_URL.drivername.startswith("postgresql"):
    raise RuntimeError("Phase 4G5 requires a PostgreSQL URL.")
if G5_URL.host != "127.0.0.1" or G5_URL.port != 5432:
    raise RuntimeError("Phase 4G5 permits only local PostgreSQL at 127.0.0.1:5432.")
if not G5_URL.database or G5_URL.database.lower() in _FORBIDDEN_DATABASES:
    raise RuntimeError("Phase 4G5 database name is not safe for a disposable test gate.")
if "g5" not in G5_URL.database.lower() or "test" not in G5_URL.database.lower():
    raise RuntimeError("Phase 4G5 database name must contain both 'g5' and 'test'.")


@pytest.fixture(scope="module")
def g5_engine():
    """Apply the real Alembic schema only to the explicitly guarded G5 database."""
    database_url = G5_URL.render_as_string(hide_password=False)
    previous_database_url = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = database_url
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
    finally:
        settings.DATABASE_URL = previous_database_url

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def g5_session_factory(g5_engine):
    factory = sessionmaker(bind=g5_engine, autoflush=False, autocommit=False)
    table_names = [name for name in inspect(g5_engine).get_table_names() if name != "alembic_version"]
    truncate = text("TRUNCATE TABLE " + ", ".join(f'"{name}"' for name in table_names) + " RESTART IDENTITY CASCADE")
    with g5_engine.begin() as connection:
        connection.execute(truncate)
    yield factory
    with g5_engine.begin() as connection:
        connection.execute(truncate)


def _claim_race(factory, execution_id):
    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def contender():
        db = factory()
        try:
            execution = db.get(Execution, execution_id)
            backend_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            barrier.wait(timeout=10)
            claimed = ExecutionRepository(db).claim_retry(execution)
            with lock:
                results.append((backend_pid, claimed is not None))
        finally:
            db.close()

    threads = [threading.Thread(target=contender), threading.Thread(target=contender)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 2 and len({item[0] for item in results}) == 2
    assert sum(item[1] for item in results) == 1


def _execute_claimed(factory, workforce, provider, execution_id, *, repurposing=False):
    db = factory()
    try:
        execution = db.get(Execution, execution_id)
        scanner = RetryScanner(ExecutionService(ExecutionRepository(db)), Scheduler())
        payload = scanner._build_retry_payload(execution)
        task = scanner.scheduler.schedule(execution.workflow_name, payload)
        task.retry_count, task.max_retries = execution.retry_count, execution.max_retries
        service = ExecutionService(ExecutionRepository(db))
        if repurposing:
            workflow = ContentRepurposingWorkflow(session_factory=factory, repurposing_service_factory=lambda session: ContentRepurposingService(session, RepurposingFactory(provider)))
        else:
            workflow = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda session: ContentGenerationService(session, GenerationFactory(provider)))
        executor = TaskExecutor(execution_service=service)
        executor.engine = type("WorkflowEngine", (), {"run": lambda _, workflow_name, payload: workflow.execute(payload)})()
        executor.workforce = None
        return RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), workforce, executor).execute(task)
    finally:
        db.close()


def test_g5_database_guard_and_real_schema(g5_engine):
    """Fail closed before any race/restart scenario can touch a non-test database."""
    assert G5_URL.host == "127.0.0.1"
    assert G5_URL.port == 5432
    assert "g5" in G5_URL.database.lower() and "test" in G5_URL.database.lower()
    assert G5_URL.password is None or isinstance(G5_URL.password, str)

    with g5_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision
        tables = set(inspect(g5_engine).get_table_names())
    assert {
        "missions",
        "executions",
        "workers",
        "content_briefs",
        "content_generation_runs",
        "generated_content_artifacts",
        "content_evaluations",
        "content_repurposing_runs",
    }.issubset(tables)


@pytest.mark.parametrize("second_result,expected", [
    (generation_success("A customer says this is helpful."), "COMPLETED"),
    (generation_timeout(), "RETRY_WAIT"),
    (generation_timeout(ProviderFailureCategory.AUTHENTICATION), "FAILED"),
])
def test_generation_postgresql_claim_race_and_restart(g5_session_factory, second_result, expected):
    db = g5_session_factory()
    try:
        run = generation_ready(db)
    finally:
        db.close()
    provider = GenerationProvider([generation_timeout(), second_result])
    launcher, manager = generation_launch(g5_session_factory, provider)
    first = launcher.launch(run.id)
    db = g5_session_factory()
    try:
        execution = db.query(Execution).filter_by(mission_id=first.mission_id).one()
        execution.next_retry_at = None; db.commit(); execution_id = execution.id
    finally:
        db.close()
    _claim_race(g5_session_factory, execution_id)
    _execute_claimed(g5_session_factory, manager.workforce, provider, execution_id)
    db = g5_session_factory()
    try:
        mission = db.get(MissionRecord, first.mission_id); durable_run = db.get(ContentGenerationRun, run.id); worker = db.get(Worker, "Content Writer")
        worker_state = "BUSY" if expected == "RETRY_WAIT" else "ONLINE"
        assert (mission.status, durable_run.status, worker.status) == (expected, expected, worker_state)
        assert provider.calls == 2
        if expected == "COMPLETED":
            assert worker.current_mission_id is None and db.query(GeneratedContentArtifact).count() == db.query(ContentEvaluation).count() == 1
        else:
            assert db.query(GeneratedContentArtifact).count() == db.query(ContentEvaluation).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize("second_result,expected", [
    (repurposing_success("A customer says this is helpful."), "COMPLETED"),
    (repurposing_failure(ProviderFailureCategory.RATE_LIMIT), "RETRY_WAIT"),
    (repurposing_failure(ProviderFailureCategory.AUTHENTICATION), "FAILED"),
])
def test_repurposing_postgresql_claim_race_and_restart(g5_session_factory, second_result, expected):
    db = g5_session_factory()
    try:
        repurposing_run, generation_run = repurposing_ready(db)
        repurposing_id, generation_id = repurposing_run.id, generation_run.id
    finally:
        db.close()

    provider = RepurposingProvider([repurposing_failure(ProviderFailureCategory.TIMEOUT), second_result])
    launcher, manager = repurposing_launch(g5_session_factory, provider)
    first = launcher.launch(repurposing_id)
    db = g5_session_factory()
    try:
        execution = db.query(Execution).filter_by(mission_id=first.mission_id).one(); execution.next_retry_at = None; db.commit(); execution_id = execution.id
    finally: db.close()
    _claim_race(g5_session_factory, execution_id)
    _execute_claimed(g5_session_factory, manager.workforce, provider, execution_id, repurposing=True)
    db = g5_session_factory()
    try:
        mission = db.get(MissionRecord, first.mission_id); repurposing = db.get(ContentRepurposingRun, repurposing_id); generation = db.get(ContentGenerationRun, generation_id); worker = db.get(Worker, "Content Writer")
        worker_state = "BUSY" if expected == "RETRY_WAIT" else "ONLINE"; repurposing_state = "RUNNING" if expected == "RETRY_WAIT" else expected
        assert (mission.status, repurposing.status, generation.status, worker.status) == (expected, repurposing_state, expected, worker_state)
        assert provider.calls == 2
    finally: db.close()


def test_generation_full_fresh_engine_restart(g5_engine, g5_session_factory):
    db = g5_session_factory()
    try:
        run = generation_ready(db)
    finally:
        db.close()
    provider = GenerationProvider([generation_timeout(), generation_success()])
    launcher, _ = generation_launch(g5_session_factory, provider)
    first = launcher.launch(run.id)
    db = g5_session_factory()
    try:
        execution = db.query(Execution).filter_by(mission_id=first.mission_id).one()
        old_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one(); execution_id = execution.id; run_id = run.id
    finally:
        db.close()
    g5_engine.dispose()
    recovery_engine = create_engine(G5_URL.render_as_string(hide_password=False), pool_pre_ping=True)
    recovery_factory = sessionmaker(bind=recovery_engine, autoflush=False, autocommit=False)
    try:
        probe = recovery_factory()
        try: assert probe.execute(text("SELECT pg_backend_pid()")).scalar_one() != old_pid
        finally: probe.close()
        _claim_race(recovery_factory, execution_id)
        _execute_claimed(recovery_factory, WorkforceManager(load_defaults=True), provider, execution_id)
        verify = recovery_factory()
        try:
            mission = verify.get(MissionRecord, first.mission_id); durable = verify.get(ContentGenerationRun, run_id); worker = verify.get(Worker, "Content Writer")
            assert (mission.status, durable.status, worker.status, worker.current_mission_id) == ("COMPLETED", "COMPLETED", "ONLINE", None)
            assert provider.calls == 2 and verify.query(GeneratedContentArtifact).count() == verify.query(ContentEvaluation).count() == 1
        finally: verify.close()
    finally:
        recovery_engine.dispose()


def test_repurposing_full_fresh_engine_restart(g5_engine, g5_session_factory):
    db = g5_session_factory()
    try:
        rep, generation = repurposing_ready(db); rep_id, generation_id = rep.id, generation.id
    finally: db.close()
    provider = RepurposingProvider([repurposing_failure(ProviderFailureCategory.TIMEOUT), repurposing_success()])
    launcher, _ = repurposing_launch(g5_session_factory, provider); first = launcher.launch(rep_id)
    db = g5_session_factory()
    try:
        execution = db.query(Execution).filter_by(mission_id=first.mission_id).one(); old_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one(); execution_id = execution.id
    finally: db.close()
    g5_engine.dispose(); recovery_engine = create_engine(G5_URL.render_as_string(hide_password=False), pool_pre_ping=True); recovery_factory = sessionmaker(bind=recovery_engine, autoflush=False, autocommit=False)
    try:
        probe = recovery_factory()
        try: assert probe.execute(text("SELECT pg_backend_pid()")).scalar_one() != old_pid
        finally: probe.close()
        _claim_race(recovery_factory, execution_id)
        _execute_claimed(recovery_factory, WorkforceManager(load_defaults=True), provider, execution_id, repurposing=True)
        verify = recovery_factory()
        try:
            mission = verify.get(MissionRecord, first.mission_id); rep = verify.get(ContentRepurposingRun, rep_id); gen = verify.get(ContentGenerationRun, generation_id); worker = verify.get(Worker, "Content Writer")
            assert (mission.status, rep.status, gen.status, worker.status, worker.current_mission_id) == ("COMPLETED", "COMPLETED", "COMPLETED", "ONLINE", None)
            assert provider.calls == 2 and verify.query(GeneratedContentArtifact).count() == verify.query(ContentEvaluation).count() == 2
        finally: verify.close()
    finally: recovery_engine.dispose()
