from datetime import datetime, timezone
import socket

import pytest

from app.content_intelligence.generation_contracts import GeneratedClaim, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.content_intelligence.repurposing_service import ContentRepurposingService
from app.executor.executor import TaskExecutor
from app.mission.manager import MissionManager
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.content_brief_service import ContentBriefService
from app.services.content_repurposing_mission_launch_service import ContentRepurposingMissionLaunchService
from app.services.execution_service import ExecutionService
from app.workflows.content.content_repurposing_workflow import ContentRepurposingWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus


@pytest.fixture(autouse=True)
def forbid_configured_database(monkeypatch):
    import app.database.session as database_session
    from app.ai.content_generation.factory import ContentGenerationProviderFactory
    import app.workflows.content.content_repurposing_workflow as workflow_module
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("configured database")
        raise AssertionError("configured SessionLocal must not be used")
    def forbidden_external_access(*args, **kwargs):
        calls.append("external access")
        raise AssertionError("network or real content provider must not be used")
    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            calls.append("configured engine")
            raise AssertionError("configured engine must not be used")
    defaults = workflow_module.ContentRepurposingWorkflow.__init__.__defaults__
    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden_external_access)
    monkeypatch.setattr(socket.socket, "connect", forbidden_external_access)
    monkeypatch.setattr(ContentGenerationProviderFactory, "create", forbidden_external_access)
    monkeypatch.setattr(workflow_module.ContentRepurposingWorkflow.__init__, "__defaults__", (forbidden, *defaults[1:]))
    yield
    assert calls == []


class Provider:
    def __init__(self, results): self.results = list(results); self.calls = 0
    def generate(self, *args): self.calls += 1; return self.results.pop(0)


class Factory:
    def __init__(self, provider): self.provider = provider
    def create(self, name): assert name == "openai"; return self.provider


class Engine:
    def __init__(self, workflow): self.workflow = workflow
    def run(self, workflow_name, payload): assert workflow_name == "content_repurpose"; return self.workflow.execute(payload)


def success(body="The program pays 20% commission."):
    return ProviderGenerationResult(True, StructuredGeneratedContent("Variant", "Hook", body, "CHECK_DETAILS", "This contains affiliate links and may earn a commission.", (GeneratedClaim("Program pays 20%", ("evidence",)),)))


def failure(category):
    return ProviderGenerationResult(False, failure=ProviderFailure(category, "safe provider failure"))


def ready_run(db):
    now = datetime.now(timezone.utc)
    discovery = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="PERCENT", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    source_generation = ContentGenerationRun(id="source-generation", content_brief_id="brief", idempotency_key="source-generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    evidence = EvidenceObservation(id="evidence", candidate_id="candidate", claim_type="commission_percent", observed_value=20, source_url="https://example.com", source_type="official", excerpt="20% commission", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    source = GeneratedContentArtifact(id="source", generation_run_id="source-generation", content_brief_id="brief", content_type="ARTICLE", title="Source", hook="Source hook", body="The program pays 20% commission.", call_to_action="CHECK_DETAILS", affiliate_disclosure="This contains affiliate links and may earn a commission.", claims=[{"text": "Program pays 20%", "source_evidence_ids": ["evidence"]}], status="GENERATED", created_at=now, updated_at=now)
    evaluation = ContentEvaluation(id="source-evaluation", artifact_id="source", content_brief_id="brief", generation_run_id="source-generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)
    db.add_all([discovery, candidate, brief, source_generation, evidence]); db.flush()
    db.add(source); db.flush()
    db.add(evaluation); db.flush()
    db.add(ContentBriefEvidence(id="link", content_brief_id="brief", evidence_observation_id="evidence", usage_role="ECONOMICS", created_at=now)); db.commit()
    parameters = {"temperature": .4, "max_output_tokens": 321, "operation": "repurpose", "source_artifact_id": "source", "source_evaluation_id": "source-evaluation", "target_content_type": "SOCIAL_POST", "channel_intent": "SOCIAL", "tone_constraints": "concise friendly", "format_constraints": "one paragraph"}
    generation = ContentBriefService(db).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters=parameters)
    repurposing = ContentRepurposingRun(source_artifact_id="source", source_evaluation_id="source-evaluation", generation_run_id=generation.id, target_content_type="SOCIAL_POST", channel_intent="SOCIAL", status="CREATED")
    db.add(repurposing); db.commit(); db.refresh(repurposing)
    return repurposing, generation


def launch(factory, provider, workers=True):
    workforce = WorkforceManager(load_defaults=workers)
    workflow = ContentRepurposingWorkflow(session_factory=factory, repurposing_service_factory=lambda db: ContentRepurposingService(db, Factory(provider)))
    manager = MissionManager(workforce=workforce, session_factory=factory); manager.executor.engine = Engine(workflow)
    return ContentRepurposingMissionLaunchService(mission_manager=manager), manager


def retry_once(factory, workforce, provider):
    db = factory()
    try:
        service = ExecutionService(ExecutionRepository(db))
        for execution in db.query(Execution).filter_by(status="QUEUED").all(): execution.next_retry_at = datetime.now(timezone.utc)
        db.commit()
        workflow = ContentRepurposingWorkflow(session_factory=factory, repurposing_service_factory=lambda session: ContentRepurposingService(session, Factory(provider)))
        executor = TaskExecutor(execution_service=service); executor.engine = Engine(workflow); executor.workforce = None
        tasks = RetryScanner(service, Scheduler()).scan_once(limit=10)
        coordinator = RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), workforce, executor)
        return (coordinator.execute(tasks[0]) if tasks else None), len(tasks)
    finally:
        db.close()


def durable(factory, mission_id, repurposing_id):
    db = factory()
    try:
        row = db.get(ContentRepurposingRun, repurposing_id)
        return db.get(MissionRecord, mission_id), db.query(Execution).filter_by(mission_id=mission_id).one(), row, db.get(ContentGenerationRun, row.generation_run_id), db.get(Worker, "Content Writer"), db.query(GeneratedContentArtifact).count(), db.query(ContentEvaluation).count()
    finally:
        db.close()


@pytest.mark.parametrize("body,decision", [("The program pays 20% commission.", "APPROVED"), ("Act now to learn about the program.", "REVISION_REQUIRED"), ("A customer says this is helpful.", "REJECTED")])
def test_successful_repurposing_mission_is_idempotent_for_editorial_outcomes(db_session, db_session_factory, body, decision):
    repurposing, generation = ready_run(db_session); provider = Provider([success(body)]); launcher, _ = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id); second = launcher.launch(repurposing.id)
    mission, execution, row, linked, worker, artifacts, evaluations = durable(db_session_factory, first.mission_id, repurposing.id)
    assert first.mission_id == second.mission_id == mission.id and first.idempotency_key == f"content-repurposing:{repurposing.id}"
    assert (mission.status, execution.status, row.status, linked.status) == ("COMPLETED", "COMPLETED", "COMPLETED", "COMPLETED")
    assert first.result_data["evaluation_decision"] == decision and provider.calls == 1 and artifacts == evaluations == 2
    assert row.generation_run_id == generation.id and worker.status == WorkerStatus.ONLINE.value and worker.missions_completed == 1


def test_waiting_worker_and_existing_mission_lookup_precede_mutable_state(db_session, db_session_factory):
    repurposing, _ = ready_run(db_session); provider = Provider([success()]); launcher, _ = launch(db_session_factory, provider, workers=False)
    first = launcher.launch(repurposing.id); second = launcher.launch(repurposing.id)
    mission, executions = db_session.get(MissionRecord, first.mission_id), db_session.query(Execution).filter_by(mission_id=first.mission_id).all()
    assert first.mission_id == second.mission_id and mission.status == "WAITING_FOR_WORKER" and executions == [] and provider.calls == 0
    row = db_session.get(ContentRepurposingRun, repurposing.id); row.status = "FAILED"; db_session.commit()
    assert launcher.launch(repurposing.id).mission_id == first.mission_id


def test_retry_resume_keeps_repurposing_running_and_reuses_link(db_session, db_session_factory):
    repurposing, generation = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), success()]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id); before = durable(db_session_factory, first.mission_id, repurposing.id)
    assert (before[0].status, before[1].status, before[2].status, before[3].status) == ("RETRY_WAIT", "QUEUED", "RUNNING", "RETRY_WAIT")
    result, claimed = retry_once(db_session_factory, manager.workforce, provider); after = durable(db_session_factory, first.mission_id, repurposing.id)
    assert result is not None and claimed == 1 and (after[0].status, after[1].status, after[2].status, after[3].status) == ("COMPLETED", "COMPLETED", "COMPLETED", "COMPLETED")
    assert after[2].generation_run_id == generation.id and provider.calls == 2 and after[5] == after[6] == 2 and after[4].status == WorkerStatus.ONLINE.value


def test_second_retryable_failure_returns_to_retry_wait(db_session, db_session_factory):
    repurposing, _ = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), failure(ProviderFailureCategory.RATE_LIMIT)]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id); retry_once(db_session_factory, manager.workforce, provider); states = durable(db_session_factory, first.mission_id, repurposing.id)
    assert (states[0].status, states[1].status, states[2].status, states[3].status) == ("RETRY_WAIT", "QUEUED", "RUNNING", "RETRY_WAIT") and states[5] == states[6] == 1


def test_retry_exhaustion_is_terminal(db_session, db_session_factory):
    repurposing, _ = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), failure(ProviderFailureCategory.TIMEOUT), failure(ProviderFailureCategory.TIMEOUT)]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id); retry_once(db_session_factory, manager.workforce, provider); retry_once(db_session_factory, manager.workforce, provider); terminal = durable(db_session_factory, first.mission_id, repurposing.id)
    assert (terminal[0].status, terminal[1].status, terminal[2].status, terminal[3].status) == ("FAILED", "FAILED", "FAILED", "FAILED") and terminal[4].status == WorkerStatus.ONLINE.value


def test_restart_like_recovery_reuses_the_same_durable_lineage(db_session, db_session_factory):
    repurposing, generation = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), success()]); launcher, _ = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id)
    result, claimed = retry_once(db_session_factory, WorkforceManager(load_defaults=True), provider)
    states = durable(db_session_factory, first.mission_id, repurposing.id)
    assert result is not None and claimed == 1 and provider.calls == 2
    assert states[0].id == first.mission_id and states[2].id == repurposing.id and states[3].id == generation.id
    assert (states[0].status, states[1].status, states[2].status, states[3].status) == ("COMPLETED", "COMPLETED", "COMPLETED", "COMPLETED")


@pytest.mark.parametrize("sequence", [[failure(ProviderFailureCategory.AUTHENTICATION)], [failure(ProviderFailureCategory.TIMEOUT), failure(ProviderFailureCategory.AUTHENTICATION)]])
def test_permanent_failure_is_terminal_on_initial_or_retry(db_session, db_session_factory, sequence):
    repurposing, _ = ready_run(db_session); provider = Provider(sequence); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(repurposing.id)
    if len(sequence) == 2: retry_once(db_session_factory, manager.workforce, provider)
    states = durable(db_session_factory, first.mission_id, repurposing.id)
    assert (states[0].status, states[1].status, states[2].status, states[3].status) == ("FAILED", "FAILED", "FAILED", "FAILED") and states[4].status == WorkerStatus.ONLINE.value


def test_unclaimed_competing_and_stale_retry_cannot_regenerate(db_session, db_session_factory):
    repurposing, _ = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), success()]); launcher, manager = launch(db_session_factory, provider); first = launcher.launch(repurposing.id)
    direct = ContentRepurposingWorkflow(session_factory=db_session_factory, repurposing_service_factory=lambda db: ContentRepurposingService(db, Factory(provider))).execute({"content_repurposing_run_id": repurposing.id})
    assert direct.success is False and provider.calls == 1
    result, claimed = retry_once(db_session_factory, manager.workforce, provider); assert result is not None and claimed == 1
    _, execution, _, _, _, artifacts, evaluations = durable(db_session_factory, first.mission_id, repurposing.id)
    stale = ContentRepurposingWorkflow(session_factory=db_session_factory, repurposing_service_factory=lambda db: ContentRepurposingService(db, Factory(provider))).execute({"content_repurposing_run_id": repurposing.id, "execution_id": execution.id, "mission_id": first.mission_id, "worker_name": "Content Writer", "retry_count": 1, "max_retries": 3})
    assert stale.success is False and provider.calls == 2 and artifacts == evaluations == 2


def test_competing_scanners_claim_once_and_sessions_are_closed(db_session, db_session_factory):
    sessions = []
    class TrackedSession:
        def __init__(self): self.session = db_session_factory(); self.closed = False
        def close(self): self.closed = True; self.session.close()
        def __getattr__(self, name): return getattr(self.session, name)
    def factory():
        session = TrackedSession(); sessions.append(session); return session

    repurposing, _ = ready_run(db_session); provider = Provider([failure(ProviderFailureCategory.TIMEOUT), success()]); launcher, manager = launch(factory, provider); first = launcher.launch(repurposing.id)
    db = factory()
    try:
        service = ExecutionService(ExecutionRepository(db))
        execution = db.query(Execution).filter_by(mission_id=first.mission_id).one(); execution.next_retry_at = datetime.now(timezone.utc); db.commit()
        scanner = RetryScanner(service, Scheduler()); first_tasks = scanner.scan_once(limit=10); second_tasks = scanner.scan_once(limit=10)
        assert len(first_tasks) == 1 and second_tasks == []
        workflow = ContentRepurposingWorkflow(session_factory=factory, repurposing_service_factory=lambda session: ContentRepurposingService(session, Factory(provider)))
        executor = TaskExecutor(execution_service=service); executor.engine = Engine(workflow); executor.workforce = None
        RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), manager.workforce, executor).execute(first_tasks[0])
    finally:
        db.close()
    states = durable(factory, first.mission_id, repurposing.id)
    assert provider.calls == 2 and states[5] == states[6] == 2 and states[4].status == WorkerStatus.ONLINE.value
    assert len(sessions) >= 3 and len({id(session) for session in sessions}) == len(sessions) and all(session.closed for session in sessions)
