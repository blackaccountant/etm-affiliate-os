"""Guarded local-G5 proof for reconciliation ownership, recovery, and fencing."""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import DistributionAdapterMetadata, DistributionStatusLookupState, DistributionStatusResult
from app.models.execution import Execution
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.content_distribution_reconciliation_mission_launch_service import ContentDistributionReconciliationMissionLaunchService
from app.services.distribution_run_service import DistributionRunService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.execution_runtime_context import current_execution_runtime_context
from app.task_queue.task import Task
from app.mission.manager import MissionManager
from app.workflows.distribution.distribution_publish_workflow import DistributionPublishWorkflow
from app.workflows.distribution.distribution_reconcile_workflow import DistributionReconcileWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo
from tests.test_milestone_5_phase5b_distribution_domain import request


_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Phase 5E.1B requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("Phase 5E.1B requires the guarded local G5 test database.")


@pytest.fixture(scope="module")
def engine():
    old = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = _url.render_as_string(hide_password=False)
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    finally:
        settings.DATABASE_URL = old
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    tables = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{name}\"' for name in tables) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Adapter(DistributionAdapter):
    def __init__(self, state=DistributionStatusLookupState.PUBLISHED):
        self.state = state
        self.publish_calls = 0
        self.lookup_calls = 0
        self.contexts = []

    @property
    def metadata(self):
        return DistributionAdapterMetadata("fake", True, True)

    def validate_target(self, request):
        raise AssertionError("proof paths must not validate for publication")

    def publish(self, request):
        self.publish_calls += 1
        raise AssertionError("proof paths must never publish")

    def get_publish_status(self, request):
        self.lookup_calls += 1
        self.contexts.append(current_execution_runtime_context())
        now = datetime.now(timezone.utc)
        return DistributionStatusResult(self.state, "post" if self.state is DistributionStatusLookupState.PUBLISHED else None, "https://example.invalid/post" if self.state is DistributionStatusLookupState.PUBLISHED else None, now if self.state is DistributionStatusLookupState.PUBLISHED else None, {"platform_status": self.state.value})


def source(db):
    """Seed the approved lineage in FK order for real PostgreSQL enforcement."""
    now = datetime.now(timezone.utc)
    db.add(DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now))
    db.flush()
    db.add(DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentGenerationRun(id="generation", content_brief_id="brief", idempotency_key="generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now))
    db.flush()
    db.add(GeneratedContentArtifact(id="artifact", generation_run_id="generation", content_brief_id="brief", content_type="ARTICLE", title="Title", hook="Hook", body="Body", call_to_action="CHECK_DETAILS", affiliate_disclosure="Affiliate disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentEvaluation(id="evaluation", artifact_id="artifact", content_brief_id="brief", generation_run_id="generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now))
    db.commit()


def run(factory, *, status, workflow):
    db = factory()
    try:
        source(db)
        row = DistributionRunService(db).create(request(platform="fake"))
        row.status = status
        db.commit()
        missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
        mission = missions.create(str(uuid4()), "Distribution", "proof", workflow, input_data={"distribution_run_id": row.id}, current_worker_name="Worker")
        missions.update_status(mission.id, "RUNNING", current_worker_name="Worker")
        workers.create("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE)
        assert workers.claim("Worker", mission.id)
        execution = executions.create(workflow, "RUNNING", mission.id, mission.name, "Worker", input_data=json.dumps({"distribution_run_id": row.id}))
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        assert executions.acquire_lease(authority, 600)
        return row.id, mission.id, authority
    finally:
        db.close()


def manager(factory, workflow):
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE))
    value = MissionManager(workforce=workforce, session_factory=factory)
    value.executor.engine = type("Engine", (), {"run": lambda _, workflow_name, payload: workflow.execute(payload)})()
    return value


def expire(factory, execution_id):
    db = factory()
    try:
        db.execute(text("UPDATE executions SET lease_expires_at = NOW() - INTERVAL '2 minutes' WHERE id = :id"), {"id": execution_id})
        db.commit()
    finally:
        db.close()


def reconcile_workflow(factory, adapter):
    registry = DistributionAdapterRegistry()
    registry.register(adapter)
    return DistributionReconcileWorkflow(factory, registry)


def publish_workflow(factory, adapter):
    registry = DistributionAdapterRegistry()
    registry.register(adapter)
    return DistributionPublishWorkflow(factory, registry)


def test_concurrent_initial_claim_has_one_winner(factory):
    db = factory()
    try:
        source(db)
        row = DistributionRunService(db).create(request(platform="fake"))
        row.status = "RECONCILIATION_REQUIRED"
        db.commit()
        authorities = []
        for index in range(2):
            execution = Execution(workflow_name="distribution_reconcile", status="RUNNING", lease_owner=f"owner-{index}", lease_generation=1, lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
            db.add(execution)
            db.flush()
            authorities.append(ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation))
        db.commit()
        run_id = row.id
    finally:
        db.close()
    barrier, results = threading.Barrier(2), []
    lock = threading.Lock()
    def contend(authority):
        session = factory()
        try:
            barrier.wait()
            result = DistributionRunRepository(session).claim_reconciliation(run_id, authority)
            with lock: results.append(result is not None)
        finally:
            session.close()
    threads = [threading.Thread(target=contend, args=(authority,)) for authority in authorities]
    [thread.start() for thread in threads]; [thread.join(15) for thread in threads]
    assert all(not thread.is_alive() for thread in threads) and results.count(True) == 1
    db = factory()
    try: assert db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id).status == "RECONCILING"
    finally: db.close()


def test_active_reconciliation_cannot_be_stolen(factory):
    run_id, mission_id, authority = run(factory, status="RECONCILING", workflow="distribution_reconcile")
    assert RunningExecutionRecoveryService(factory).recover(authority.execution_id) is None
    db = factory()
    try:
        assert db.get(Execution, authority.execution_id).status == "RUNNING"
        assert db.query(Execution).filter_by(mission_id=mission_id).count() == 1
        assert db.get(Worker, "Worker").current_mission_id == mission_id
        assert db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id).status == "RECONCILING"
    finally: db.close()


def test_concurrent_expired_reconciliation_recovery_has_one_replacement(factory):
    run_id, mission_id, old = run(factory, status="RECONCILING", workflow="distribution_reconcile")
    expire(factory, old.execution_id)
    barrier, recovered = threading.Barrier(2), []
    lock = threading.Lock()

    def contend():
        barrier.wait()
        result = RunningExecutionRecoveryService(factory).recover(old.execution_id)
        with lock:
            recovered.append(result)

    contenders = [threading.Thread(target=contend) for _ in range(2)]
    [contender.start() for contender in contenders]
    [contender.join(15) for contender in contenders]
    assert all(not contender.is_alive() for contender in contenders)
    winners = [result for result in recovered if result is not None]
    assert len(winners) == 1

    adapter = Adapter()
    assert manager(factory, reconcile_workflow(factory, adapter)).resume_recovered_mission(winners[0]).success
    db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=mission_id).order_by(Execution.id).all()
        assert len(attempts) == 2 and attempts[0].status == "ABANDONED"
        assert attempts[1].lease_generation == old.lease_generation + 1
        assert db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id).status == "COMPLETED"
        assert adapter.lookup_calls == 1 and adapter.publish_calls == 0
    finally:
        db.close()


@pytest.mark.parametrize(("outcome", "expected"), [(DistributionStatusLookupState.PUBLISHED, "COMPLETED"), (DistributionStatusLookupState.NOT_FOUND, "RETRY_WAIT"), (DistributionStatusLookupState.UNKNOWN, "RECONCILIATION_REQUIRED")])
def test_expired_reconciliation_recovers_once_and_fences_stale_business_writes(factory, outcome, expected):
    run_id, mission_id, old = run(factory, status="RECONCILING", workflow="distribution_reconcile")
    expire(factory, old.execution_id)
    recovered = RunningExecutionRecoveryService(factory).recover(old.execution_id)
    assert recovered is not None and RunningExecutionRecoveryService(factory).recover(old.execution_id) is None
    db = factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            DistributionRunRepository(db).transition_owned(run_id, old, expected_statuses=("RECONCILING",), status="COMPLETED")
    finally: db.close()
    adapter = Adapter(outcome)
    result = manager(factory, reconcile_workflow(factory, adapter)).resume_recovered_mission(recovered)
    db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=mission_id).order_by(Execution.id).all()
        assert len(attempts) == 2 and attempts[0].status == "ABANDONED"
        assert attempts[1].lease_generation == old.lease_generation + 1 and attempts[1].lease_owner != old.lease_owner
        assert db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id).status == expected
        assert adapter.lookup_calls == 1 and adapter.publish_calls == 0 and len(adapter.contexts) == 1
        assert adapter.contexts[0].is_recovery is True and result.success
    finally: db.close()


def test_active_and_expired_publishing_are_safe(factory):
    run_id, mission_id, old = run(factory, status="PUBLISHING", workflow="distribution_publish")
    adapter = Adapter()
    assert not publish_workflow(factory, adapter).execute({"distribution_run_id": run_id}).success
    with pytest.raises(RuntimeError):
        ContentDistributionReconciliationMissionLaunchService(session_factory=factory).launch(run_id)
    assert RunningExecutionRecoveryService(factory).recover(old.execution_id) is None
    expire(factory, old.execution_id)
    recovered = RunningExecutionRecoveryService(factory).recover(old.execution_id)
    assert recovered is not None
    db = factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            DistributionRunRepository(db).transition_owned(run_id, old, expected_statuses=("PUBLISHING",), status="RECONCILIATION_REQUIRED")
    finally: db.close()
    result = manager(factory, publish_workflow(factory, adapter)).resume_recovered_mission(recovered)
    db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=mission_id).all()
        row = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert result.success and row.status == "RECONCILIATION_REQUIRED" and len(attempts) == 2
        assert adapter.publish_calls == adapter.lookup_calls == 0
        assert RunningExecutionRecoveryService(factory).recover(old.execution_id) is None
    finally: db.close()


def test_runtime_context_does_not_leak_after_recovery(factory):
    run_id, _, old = run(factory, status="RECONCILING", workflow="distribution_reconcile")
    expire(factory, old.execution_id)
    recovered = RunningExecutionRecoveryService(factory).recover(old.execution_id)
    adapter = Adapter()
    manager(factory, reconcile_workflow(factory, adapter)).resume_recovered_mission(recovered)
    assert current_execution_runtime_context() is None
