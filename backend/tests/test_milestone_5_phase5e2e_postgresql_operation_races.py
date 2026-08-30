"""Guarded real-PostgreSQL races for durable distribution operations."""
import os
import threading
from uuid import uuid4
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.distribution.mission_contracts import distribution_reconciliation_mission_idempotency_key
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.content_brief import ContentBrief
from app.models.content_generation_run import ContentGenerationRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.content_evaluation import ContentEvaluation
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.content_distribution_reconciliation_mission_launch_service import ContentDistributionReconciliationMissionLaunchService
from app.services.execution_lease import ExecutionLeaseAuthority
from app.services.owned_execution_lifecycle import OwnedExecutionLifecycleCoordinator
from app.services.owned_lifecycle_participants import participant_for_workflow
from app.services.distribution_run_service import DistributionRunService
from app.services.running_execution_recovery_service import RunningExecutionRecoveryService
from app.services.durable_operation_activation_service import DurableOperationActivationService, SuccessorOperationSpec
from app.workforce.status import WorkerStatus
from tests.test_milestone_5_phase5b_distribution_domain import request

_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("Phase 5E.2E.1 requires only guarded local G5.")

@pytest.fixture(scope="module")
def engine():
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "fa1b2c3d4e5f"
        columns = {row[0] for row in c.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='distribution_runs'"))}
        assert {"publish_generation", "reconciliation_generation"} <= columns
    yield engine
    engine.dispose()

@pytest.fixture
def factory(engine):
    names = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
    with engine.begin() as c:
        c.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{name}\"' for name in names) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def _seed(factory, *, terminal=False):
    db = factory(); _lineage(db); run = DistributionRunService(db).create(request(platform="fake")); run.status = "RECONCILING" if not terminal else "RECONCILIATION_REQUIRED"
    missions, workers, executions = MissionRepository(db), WorkerRepository(db), ExecutionRepository(db)
    key = distribution_reconciliation_mission_idempotency_key(run.id)
    mission = missions.create(str(uuid4()), "Reconcile", "proof", "distribution_reconcile", input_data={"distribution_run_id": run.id}, idempotency_key=key, current_worker_name="Worker")
    workers.create("Worker", "Test", ["content_distribution"], WorkerStatus.ONLINE); assert workers.claim("Worker", mission.id)
    missions.update_status(mission.id, "RUNNING", current_worker_name="Worker")
    execution = executions.create("distribution_reconcile", "RUNNING", mission.id, mission.name, "Worker", input_data='{"distribution_run_id":"%s"}' % run.id)
    auth = ExecutionLeaseAuthority.fresh(execution.id, 1); assert executions.acquire_lease(auth, 120)
    if terminal:
        execution.status = "COMPLETED"; execution.lease_expires_at = None; mission.status = "COMPLETED"; mission.current_worker_name = None; assert workers.release("Worker", mission.id, True, commit=False)
    db.commit(); db.close(); return run.id, mission.id, auth

def _lineage(db):
    now = datetime.now(timezone.utc)
    db.add(DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)); db.flush()
    db.add(DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)); db.flush()
    db.add(ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)); db.flush()
    db.add(ContentGenerationRun(id="generation", content_brief_id="brief", idempotency_key="generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)); db.flush()
    db.add(GeneratedContentArtifact(id="artifact", generation_run_id="generation", content_brief_id="brief", content_type="ARTICLE", title="Title", hook="Hook", body="Body", call_to_action="CHECK_DETAILS", affiliate_disclosure="Affiliate disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now)); db.flush()
    db.add(ContentEvaluation(id="evaluation", artifact_id="artifact", content_brief_id="brief", generation_run_id="generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)); db.flush()

def _race(factory, action):
    barrier, outcomes = threading.Barrier(2), []
    def contender():
        try: barrier.wait(); outcomes.append(("ok", action()))
        except Exception as exc: outcomes.append(("error", type(exc).__name__))
    threads = [threading.Thread(target=contender) for _ in range(2)]
    [t.start() for t in threads]; [t.join(20) for t in threads]
    assert all(not t.is_alive() for t in threads)
    return outcomes

def test_concurrent_not_found_handoff_creates_one_followup(factory):
    run_id, mission_id, authority = _seed(factory)
    def action():
        db = factory()
        try:
            return OwnedExecutionLifecycleCoordinator(db).complete(authority, mission_id=mission_id, mission_name="Reconcile", worker_name="Worker", duration=0, result_data="{}", result_payload={"success": True, "workflow": "distribution_reconcile", "data": {"distribution_run_id": run_id, "reconciliation_state": "NOT_FOUND"}}, participant=participant_for_workflow("distribution_reconcile"))
        finally: db.close()
    outcomes = _race(factory, action); db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id); key = f"distribution-publish:{run_id}:1"; successor = db.query(MissionRecord).filter_by(idempotency_key=key).one()
        assert run.publish_generation == 1 and run.status == "CREATED" and db.query(MissionRecord).filter_by(idempotency_key=key).count() == 1 and db.query(Execution).filter_by(mission_id=successor.id).count() == 1 and db.query(MissionRecord).filter(MissionRecord.idempotency_key.like(f"distribution-publish:{run_id}:2")).count() == 0
    finally: db.close()
    assert len(outcomes) == 2

def test_concurrent_terminal_reconciliation_launch_creates_one_generation(factory):
    run_id, _, _ = _seed(factory, terminal=True)
    outcomes = _race(factory, lambda: ContentDistributionReconciliationMissionLaunchService(session_factory=factory).launch(run_id))
    db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id); key = distribution_reconciliation_mission_idempotency_key(run_id, 1); mission = db.query(MissionRecord).filter_by(idempotency_key=key).one()
        assert run.reconciliation_generation == 1 and db.query(MissionRecord).filter_by(idempotency_key=key).count() == 1 and db.query(Execution).filter_by(mission_id=mission.id).count() == 1 and db.query(MissionRecord).filter(MissionRecord.idempotency_key.like(f"distribution-reconciliation:{run_id}:2")).count() == 0
    finally: db.close()
    assert len(outcomes) == 2

def _expire_and_recover(factory, execution_id):
    db = factory()
    try:
        db.execute(text("UPDATE executions SET lease_expires_at = NOW() - INTERVAL '1 minute' WHERE id = :id"), {"id": execution_id}); db.commit()
    finally: db.close()
    return RunningExecutionRecoveryService(factory).recover(execution_id)

def test_followup_publish_committed_before_dispatch_recovers_same_mission(factory):
    run_id, mission_id, authority = _seed(factory)
    db = factory()
    try:
        result = OwnedExecutionLifecycleCoordinator(db).complete(authority, mission_id=mission_id, mission_name="Reconcile", worker_name="Worker", duration=0, result_data="{}", result_payload={"success": True, "workflow": "distribution_reconcile", "data": {"distribution_run_id": run_id, "reconciliation_state": "NOT_FOUND"}}, participant=participant_for_workflow("distribution_reconcile")); successor = result.successor
    finally: db.close()
    recovered = _expire_and_recover(factory, successor.execution_id); db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=successor.mission_id).order_by(Execution.id).all(); run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert recovered and len(attempts) == 2 and attempts[0].status == "ABANDONED" and attempts[1].mission_id == successor.mission_id and attempts[1].lease_generation > attempts[0].lease_generation and run.publish_generation == 1
    finally: db.close()

def test_reconciliation_generation_committed_before_dispatch_recovers_same_mission(factory):
    run_id, _, _ = _seed(factory, terminal=True)
    launched = ContentDistributionReconciliationMissionLaunchService(session_factory=factory).launch(run_id)
    db = factory()
    try: execution = db.query(Execution).filter_by(mission_id=launched.mission_id).one()
    finally: db.close()
    recovered = _expire_and_recover(factory, execution.id); db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=launched.mission_id).order_by(Execution.id).all(); run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert recovered and len(attempts) == 2 and attempts[0].status == "ABANDONED" and attempts[1].mission_id == launched.mission_id and attempts[1].lease_generation > attempts[0].lease_generation and run.reconciliation_generation == 1
    finally: db.close()

def test_two_recovery_contenders_create_one_replacement(factory):
    run_id, _, _ = _seed(factory, terminal=True)
    launched = ContentDistributionReconciliationMissionLaunchService(session_factory=factory).launch(run_id)
    db = factory()
    try: execution = db.query(Execution).filter_by(mission_id=launched.mission_id).one()
    finally: db.close()
    db = factory(); db.execute(text("UPDATE executions SET lease_expires_at = NOW() - INTERVAL '1 minute' WHERE id = :id"), {"id": execution.id}); db.commit(); db.close()
    outcomes = _race(factory, lambda: RunningExecutionRecoveryService(factory).recover(execution.id))
    db = factory()
    try:
        attempts = db.query(Execution).filter_by(mission_id=launched.mission_id).order_by(Execution.id).all(); run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert len(attempts) == 2 and attempts[0].status == "ABANDONED" and attempts[1].lease_generation > attempts[0].lease_generation and run.reconciliation_generation == 1
    finally: db.close()
    assert len(outcomes) == 2

def test_worker_claim_contention_leaves_one_durable_operation(factory):
    db = factory(); workers = WorkerRepository(db); workers.create("Sole", "Test", ["cap"], WorkerStatus.ONLINE); db.close()
    def activate(key):
        db = factory()
        try:
            result = DurableOperationActivationService(db).activate(SuccessorOperationSpec("Op", "proof", "worker_race", "cap", key, {})); db.commit(); return result
        except Exception: db.rollback(); raise
        finally: db.close()
    barrier, outcomes = threading.Barrier(2), []
    def contender(key):
        try: barrier.wait(); outcomes.append(("ok", activate(key)))
        except Exception as exc: outcomes.append(("error", type(exc).__name__))
    threads = [threading.Thread(target=contender, args=(f"worker-race-{n}",)) for n in range(2)]
    [t.start() for t in threads]; [t.join(20) for t in threads]; assert all(not t.is_alive() for t in threads)
    db = factory()
    try:
        owner = db.get(Worker, "Sole"); assert owner.status == "BUSY" and owner.current_mission_id and db.query(MissionRecord).count() == 1 and db.query(Execution).count() == 1
    finally: db.close()
    assert sum(kind == "ok" for kind, _ in outcomes) == 1

def test_no_worker_terminal_generation_rolls_back(factory):
    run_id, _, _ = _seed(factory, terminal=True)
    db = factory(); db.query(Worker).update({Worker.status: "OFFLINE"}); db.commit(); db.close()
    with pytest.raises(RuntimeError, match="no eligible worker"):
        ContentDistributionReconciliationMissionLaunchService(session_factory=factory).launch(run_id)
    db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert run.reconciliation_generation == 0 and db.query(MissionRecord).count() == 1 and db.query(Execution).count() == 1 and db.get(Worker, "Worker").status == "OFFLINE"
    finally: db.close()

def test_stale_authority_cannot_create_not_found_successor(factory):
    run_id, mission_id, authority = _seed(factory)
    _expire_and_recover(factory, authority.execution_id)
    db = factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            OwnedExecutionLifecycleCoordinator(db).complete(authority, mission_id=mission_id, mission_name="Reconcile", worker_name="Worker", duration=0, result_data="{}", result_payload={"success": True, "workflow": "distribution_reconcile", "data": {"distribution_run_id": run_id, "reconciliation_state": "NOT_FOUND"}}, participant=participant_for_workflow("distribution_reconcile"))
    finally: db.close()
    db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id)
        assert run.status == "RECONCILING" and run.publish_generation == run.reconciliation_generation == 0 and db.query(MissionRecord).count() == 1 and db.query(Execution).count() == 2
    finally: db.close()

def test_stale_authority_cannot_transition_reconciliation_run(factory):
    run_id, _, authority = _seed(factory)
    recovered = _expire_and_recover(factory, authority.execution_id); db = factory()
    try:
        with pytest.raises(ExecutionLeaseLostError):
            DistributionRunRepository(db).transition_owned(run_id, authority, expected_statuses=("RECONCILING",), status="RECONCILIATION_REQUIRED")
    finally: db.close()
    db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id); current = db.get(Execution, recovered.replacement_execution_id)
        assert run.status == "RECONCILING" and run.publish_generation == run.reconciliation_generation == 0 and current.lease_owner == recovered.authority.lease_owner
    finally: db.close()

def test_postgresql_reconciliation_multi_generation_history(factory):
    run_id, _, _ = _seed(factory, terminal=True); launcher = ContentDistributionReconciliationMissionLaunchService(session_factory=factory)
    first = launcher.launch(run_id)
    def terminalize(mission_id):
        db = factory()
        try:
            mission = db.get(MissionRecord, mission_id); execution = db.query(Execution).filter_by(mission_id=mission_id).one(); authority = ExecutionLeaseAuthority(execution.id, execution.lease_owner, execution.lease_generation)
            OwnedExecutionLifecycleCoordinator(db).complete(authority, mission_id=mission.id, mission_name=mission.name, worker_name=execution.worker_name, duration=0, result_data="{}", result_payload={"success": True, "workflow": "distribution_reconcile", "data": {"distribution_run_id": run_id, "reconciliation_state": "UNKNOWN"}})
        finally: db.close()
    terminalize(first.mission_id); second = launcher.launch(run_id)
    db = factory()
    try:
        run = db.get(__import__("app.models.distribution_run", fromlist=["DistributionRun"]).DistributionRun, run_id); keys = [m.idempotency_key for m in db.query(MissionRecord).order_by(MissionRecord.idempotency_key)]
        assert run.reconciliation_generation == 2 and keys == [distribution_reconciliation_mission_idempotency_key(run_id), distribution_reconciliation_mission_idempotency_key(run_id, 1), distribution_reconciliation_mission_idempotency_key(run_id, 2)] and db.get(MissionRecord, second.mission_id).status == "RUNNING"
    finally: db.close()
