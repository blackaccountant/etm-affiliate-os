from datetime import datetime, timezone
import socket

import pytest

from app.content_intelligence.generation_contracts import GeneratedClaim, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.content_intelligence.generation_service import ContentGenerationService
from app.executor.executor import TaskExecutor
from app.mission.manager import MissionManager
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
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
from app.services.content_generation_mission_launch_service import ContentGenerationMissionLaunchService
from app.services.execution_service import ExecutionService
from app.workflows.content.content_generation_workflow import ContentGenerationWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus


@pytest.fixture(autouse=True)
def forbid_configured_database(monkeypatch):
    import app.database.session as database_session
    from app.ai.content_generation.factory import ContentGenerationProviderFactory
    import app.workflows.content.content_generation_workflow as workflow_module
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
    defaults = workflow_module.ContentGenerationWorkflow.__init__.__defaults__
    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden_external_access)
    monkeypatch.setattr(socket.socket, "connect", forbidden_external_access)
    monkeypatch.setattr(ContentGenerationProviderFactory, "create", forbidden_external_access)
    monkeypatch.setattr(workflow_module.ContentGenerationWorkflow.__init__, "__defaults__", (forbidden, *defaults[1:]))
    yield
    assert calls == []


class Provider:
    def __init__(self, results): self.results = list(results); self.calls = 0
    def generate(self, *args): self.calls += 1; return self.results.pop(0)


class Factory:
    def __init__(self, provider): self.provider = provider
    def create(self, name): assert name == "openai"; return self.provider


class Engine:
    def __init__(self, workflow): self.workflow = workflow; self.calls = 0
    def run(self, workflow_name, payload):
        assert workflow_name == "content_generate"
        self.calls += 1
        return self.workflow.execute(payload)


def success(body="A grounded program description."):
    return ProviderGenerationResult(True, StructuredGeneratedContent("Title", "Hook", body, "CHECK_DETAILS", "This contains affiliate links and may earn a commission.", (GeneratedClaim("Program exists", ("evidence",)),)))


def timeout(category=ProviderFailureCategory.TIMEOUT):
    return ProviderGenerationResult(False, failure=ProviderFailure(category, "safe provider failure"))


def ready_run(db):
    now = datetime.now(timezone.utc)
    discovery = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    evidence = EvidenceObservation(id="evidence", candidate_id="candidate", claim_type="affiliate_program_exists", observed_value=True, source_url="https://example.com", source_type="official", excerpt="Affiliate program", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    db.add_all([discovery, candidate, brief, evidence]); db.flush(); db.add(ContentBriefEvidence(id="link", content_brief_id="brief", evidence_observation_id="evidence", usage_role="PRIMARY", created_at=now)); db.commit()
    return ContentBriefService(db).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": .2, "max_output_tokens": 1200})


def launch(factory, provider):
    workforce = WorkforceManager(load_defaults=True)
    workflow = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda db: ContentGenerationService(db, Factory(provider)))
    manager = MissionManager(workforce=workforce, session_factory=factory); manager.executor.engine = Engine(workflow)
    return ContentGenerationMissionLaunchService(mission_manager=manager), manager


def retry_once(factory, workforce, provider):
    db = factory()
    try:
        service = ExecutionService(ExecutionRepository(db)); scanner = RetryScanner(service, Scheduler())
        for execution in db.query(Execution).filter_by(status="QUEUED").all():
            execution.next_retry_at = datetime.now(timezone.utc)
        db.commit()
        workflow = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda session: ContentGenerationService(session, Factory(provider)))
        executor = TaskExecutor(execution_service=service); executor.engine = Engine(workflow); executor.workforce = None
        coordinator = RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), workforce, executor)
        tasks = scanner.scan_once(limit=10)
        return (coordinator.execute(tasks[0]) if tasks else None), len(tasks)
    finally:
        db.close()


def state(factory, mission_id, run_id):
    db = factory()
    try:
        return (db.get(MissionRecord, mission_id), db.query(Execution).filter_by(mission_id=mission_id).one(), db.get(ContentGenerationRun, run_id), db.get(Worker, "Content Writer"))
    finally:
        db.close()


@pytest.mark.parametrize("body,decision", [("A grounded program description.", "APPROVED"), ("Act now to learn more about the program.", "REVISION_REQUIRED"), ("A customer says this is helpful.", "REJECTED")])
def test_claimed_retry_resumes_same_run_and_completes_for_each_editorial_outcome(db_session, db_session_factory, body, decision):
    run = ready_run(db_session); provider = Provider([timeout(), success(body)]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(run.id); before = state(db_session_factory, first.mission_id, run.id)
    assert (before[0].status, before[1].status, before[2].status) == ("RETRY_WAIT", "QUEUED", "RETRY_WAIT")
    result, claimed = retry_once(db_session_factory, manager.workforce, provider); mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)
    assert result is not None and claimed == 1 and mission.status == execution.status == durable_run.status == "COMPLETED"
    assert worker.status == WorkerStatus.ONLINE.value and worker.missions_completed == 1
    assert provider.calls == 2 and db_session.query(GeneratedContentArtifact).count() == db_session.query(ContentEvaluation).count() == 1
    assert result.data["evaluation_decision"] == decision and db_session.query(MissionRecord).count() == db_session.query(ContentGenerationRun).count() == 1


def test_second_retryable_failure_stays_owned_without_new_artifact_or_run(db_session, db_session_factory):
    run = ready_run(db_session); provider = Provider([timeout(), timeout(ProviderFailureCategory.RATE_LIMIT)]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(run.id); result, claimed = retry_once(db_session_factory, manager.workforce, provider); mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)
    assert result is not None and claimed == 1
    assert (mission.status, execution.status, durable_run.status) == ("RETRY_WAIT", "QUEUED", "RETRY_WAIT")
    assert worker.status == WorkerStatus.BUSY.value and worker.current_mission_id == mission.id and provider.calls == 2
    assert db_session.query(GeneratedContentArtifact).count() == db_session.query(ContentEvaluation).count() == 0 and db_session.query(ContentGenerationRun).count() == 1


def test_retry_exhaustion_and_permanent_retry_failure_are_terminal(db_session, db_session_factory):
    run = ready_run(db_session); provider = Provider([timeout(), timeout(), timeout()]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(run.id); retry_once(db_session_factory, manager.workforce, provider); retry_once(db_session_factory, manager.workforce, provider)
    mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)
    assert mission.status == execution.status == durable_run.status == "FAILED" and worker.status == WorkerStatus.ONLINE.value and worker.missions_failed == 1
    assert provider.calls == 3 and db_session.query(GeneratedContentArtifact).count() == db_session.query(ContentEvaluation).count() == 0


def test_permanent_failure_during_claimed_retry_is_terminal(db_session, db_session_factory):
    run = ready_run(db_session); provider = Provider([timeout(), timeout(ProviderFailureCategory.AUTHENTICATION)]); launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(run.id); retry_once(db_session_factory, manager.workforce, provider); mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)
    assert mission.status == execution.status == durable_run.status == "FAILED" and worker.status == WorkerStatus.ONLINE.value and provider.calls == 2


def test_restart_like_recovery_uses_fresh_workflow_and_session(db_session, db_session_factory):
    run = ready_run(db_session)
    provider = Provider([timeout(), success()])
    launcher, manager = launch(db_session_factory, provider)
    first = launcher.launch(run.id)

    # Deliberately discard the initial orchestration objects before recovery.
    recovered_workforce = WorkforceManager(load_defaults=True)
    result, claimed = retry_once(db_session_factory, recovered_workforce, provider)
    mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)

    assert result is not None and claimed == 1 and provider.calls == 2
    assert mission.id == first.mission_id and execution.mission_id == first.mission_id
    assert durable_run.id == run.id and (mission.status, execution.status, durable_run.status) == ("COMPLETED", "COMPLETED", "COMPLETED")
    assert worker.status == WorkerStatus.ONLINE.value and worker.current_mission_id is None


def test_initial_and_retry_invocations_close_distinct_sessions(db_session, db_session_factory):
    sessions = []

    class TrackedSession:
        def __init__(self):
            self.session = db_session_factory()
            self.closed = False

        def close(self):
            self.closed = True
            self.session.close()

        def __getattr__(self, name):
            return getattr(self.session, name)

    def tracked_factory():
        tracked = TrackedSession()
        sessions.append(tracked)
        return tracked

    run = ready_run(db_session)
    provider = Provider([timeout(), success()])
    launcher, manager = launch(tracked_factory, provider)
    first = launcher.launch(run.id)
    result, claimed = retry_once(tracked_factory, manager.workforce, provider)

    assert result is not None and claimed == 1 and provider.calls == 2
    assert len(sessions) >= 2 and len({id(session) for session in sessions}) == len(sessions)
    assert all(session.closed for session in sessions)
    mission, execution, durable_run, _ = state(tracked_factory, first.mission_id, run.id)
    assert (mission.status, execution.status, durable_run.status) == ("COMPLETED", "COMPLETED", "COMPLETED")


def test_unclaimed_and_competing_retry_attempts_cannot_resume_or_call_twice(db_session, db_session_factory):
    run = ready_run(db_session); provider = Provider([timeout(), success()]); launcher, manager = launch(db_session_factory, provider); first = launcher.launch(run.id)
    direct = ContentGenerationWorkflow(session_factory=db_session_factory, generation_service_factory=lambda db: ContentGenerationService(db, Factory(provider))).execute({"content_generation_run_id": run.id})
    db_session.rollback(); db_session.expire_all()
    assert direct.success is False and provider.calls == 1 and db_session.get(ContentGenerationRun, run.id).status == "RETRY_WAIT"
    db = db_session_factory()
    try:
        service = ExecutionService(ExecutionRepository(db))
        for execution in db.query(Execution).filter_by(status="QUEUED").all():
            execution.next_retry_at = datetime.now(timezone.utc)
        db.commit()
        first_tasks = RetryScanner(service, Scheduler()).scan_once(limit=10)
        second_tasks = RetryScanner(service, Scheduler()).scan_once(limit=10)
        assert len(first_tasks) == 1 and second_tasks == []
        workflow = ContentGenerationWorkflow(session_factory=db_session_factory, generation_service_factory=lambda s: ContentGenerationService(s, Factory(provider)))
        executor = TaskExecutor(execution_service=service); executor.engine = Engine(workflow); executor.workforce = None
        RetryLifecycleCoordinator(db, service, MissionRepository(db), WorkerRepository(db), manager.workforce, executor).execute(first_tasks[0])
    finally:
        db.close()
    mission, execution, durable_run, worker = state(db_session_factory, first.mission_id, run.id)
    assert mission.status == execution.status == durable_run.status == "COMPLETED" and provider.calls == 2 and db_session.query(GeneratedContentArtifact).count() == 1


def test_stale_claimed_retry_does_not_regenerate(db_session, db_session_factory):
    run = ready_run(db_session); provider = Provider([timeout(), success()]); launcher, manager = launch(db_session_factory, provider); first = launcher.launch(run.id)
    retry_once(db_session_factory, manager.workforce, provider)
    _, execution, _, _ = state(db_session_factory, first.mission_id, run.id)
    result = ContentGenerationWorkflow(session_factory=db_session_factory, generation_service_factory=lambda db: ContentGenerationService(db, Factory(provider))).execute({"content_generation_run_id": run.id, "execution_id": execution.id, "mission_id": first.mission_id, "worker_name": "Content Writer", "retry_count": 1, "max_retries": 3})
    assert result.success is False and provider.calls == 2 and db_session.query(GeneratedContentArtifact).count() == db_session.query(ContentEvaluation).count() == 1
