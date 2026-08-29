from datetime import datetime, timezone
import socket
from types import SimpleNamespace

import pytest

from app.content_intelligence.generation_contracts import GeneratedClaim, GenerationParameters, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.content_intelligence.generation_service import ContentGenerationService
from app.mission.manager import MissionManager
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.mission_repository import MissionRepository
from app.services.content_brief_service import ContentBriefService
from app.services.content_generation_mission_launch_service import ContentGenerationMissionLaunchService
from app.workflows.content.content_generation_workflow import ContentGenerationWorkflow
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus


@pytest.fixture(autouse=True)
def forbid_configured_database(monkeypatch):
    """The real Mission lifecycle in this suite must use only injected SQLite sessions."""
    import app.database.session as database_session
    from app.ai.content_generation.factory import ContentGenerationProviderFactory
    import app.workflows.content.content_generation_workflow as generation_workflow

    calls = []

    def forbidden_configured_session(*args, **kwargs):
        calls.append("SessionLocal")
        raise AssertionError("configured SessionLocal must not be used by focused 4G tests")

    def forbidden_external_access(*args, **kwargs):
        calls.append("external access")
        raise AssertionError("network or real content provider must not be used by focused 4G tests")

    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            calls.append("engine")
            raise AssertionError("configured database engine must not be used by focused 4G tests")

    defaults = generation_workflow.ContentGenerationWorkflow.__init__.__defaults__
    monkeypatch.setattr(database_session, "SessionLocal", forbidden_configured_session)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden_external_access)
    monkeypatch.setattr(socket.socket, "connect", forbidden_external_access)
    monkeypatch.setattr(ContentGenerationProviderFactory, "create", forbidden_external_access)
    monkeypatch.setattr(generation_workflow.ContentGenerationWorkflow.__init__, "__defaults__", (forbidden_configured_session, *defaults[1:]))
    yield
    assert calls == []


class FakeProvider:
    def __init__(self, result): self.result = result; self.calls = 0
    def generate(self, *args): self.calls += 1; return self.result


class FakeFactory:
    def __init__(self, provider): self.provider = provider
    def create(self, name):
        assert name == "openai"
        return self.provider


class WorkflowEngine:
    def __init__(self, workflow): self.workflow = workflow; self.calls = 0
    def run(self, workflow_name, payload):
        assert workflow_name == "content_generate"; self.calls += 1
        return self.workflow.execute(payload)


def _content(body="A grounded program description."):
    return ProviderGenerationResult(True, StructuredGeneratedContent("Title", "Hook", body, "CHECK_DETAILS", "This contains affiliate links and may earn a commission.", (GeneratedClaim("Program exists", ("evidence",)),)))


def _ready_run(db, *, status="CREATED"):
    now = datetime.now(timezone.utc)
    discovery = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    evidence = EvidenceObservation(id="evidence", candidate_id="candidate", claim_type="affiliate_program_exists", observed_value=True, source_url="https://example.com", source_type="official", excerpt="Affiliate program", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    db.add_all([discovery, candidate, brief, evidence]); db.flush(); db.add(ContentBriefEvidence(id="link", content_brief_id="brief", evidence_observation_id="evidence", usage_role="PRIMARY", created_at=now)); db.commit()
    run = ContentBriefService(db).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": .2, "max_output_tokens": 1200})
    if status != "CREATED":
        run.transition_to("RUNNING")
        if status != "RUNNING": run.transition_to(status)
        db.commit()
    return run


def _launch_service(factory, provider, *, workers=True):
    workforce = WorkforceManager(load_defaults=workers)
    workflow = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda db: ContentGenerationService(db, FakeFactory(provider)))
    manager = MissionManager(workforce=workforce, session_factory=factory)
    manager.executor.engine = WorkflowEngine(workflow)
    return ContentGenerationMissionLaunchService(mission_manager=manager), manager


def _durable(db, mission_id):
    db.expire_all()
    return db.get(MissionRecord, mission_id), db.query(Execution).filter_by(mission_id=mission_id).all(), db.get(Worker, "Content Writer")


@pytest.mark.parametrize("body,decision", [("A grounded program description.", "APPROVED"), ("Act now to learn more about the program.", "REVISION_REQUIRED"), ("A customer says this program is helpful.", "REJECTED")])
def test_generation_mission_completes_for_all_editorial_decisions(db_session, db_session_factory, body, decision):
    run = _ready_run(db_session); provider = FakeProvider(_content(body)); launcher, _ = _launch_service(db_session_factory, provider)
    result = launcher.launch(run.id)
    mission, executions, worker = _durable(db_session, result.mission_id)
    assert result.mission_status == mission.status == "COMPLETED" and result.result_success is True
    assert result.workflow == "content_generate" and result.required_capability == "content_generation"
    assert result.idempotency_key == f"content-generation:{run.id}" and result.result_data["evaluation_decision"] == decision
    assert result.result_data["content_brief_id"] == "brief" and result.result_data["content_generation_run_id"] == run.id
    assert len(executions) == 1 and executions[0].status == "COMPLETED" and provider.calls == 1
    assert worker.status == WorkerStatus.ONLINE.value and worker.current_mission_id is None and worker.missions_completed == 1
    assert db_session.query(GeneratedContentArtifact).count() == 1
    assert db_session.query(Product).count() == db_session.query(AffiliateProgram).count() == db_session.query(AffiliateOpportunity).count() == db_session.query(AffiliateContentAsset).count() == 0


def test_waiting_worker_creates_no_execution_and_duplicate_launch_is_stable(db_session, db_session_factory):
    run = _ready_run(db_session); provider = FakeProvider(_content()); launcher, manager = _launch_service(db_session_factory, provider, workers=False)
    first = launcher.launch(run.id); second = launcher.launch(run.id)
    mission, executions, _ = _durable(db_session, first.mission_id)
    assert first.mission_status == second.mission_status == mission.status == "WAITING_FOR_WORKER"
    assert first.mission_id == second.mission_id and first.worker_name is second.worker_name is None
    assert executions == [] and provider.calls == 0 and manager.executor.engine.calls == 0
    assert db_session.get(ContentGenerationRun, run.id).status == "CREATED"


@pytest.mark.parametrize("run_status", ["RUNNING", "RETRY_WAIT", "COMPLETED", "FAILED"])
def test_existing_mission_is_returned_before_mutable_generation_run_validation(db_session, db_session_factory, run_status):
    run = _ready_run(db_session, status=run_status); provider = FakeProvider(_content()); launcher, manager = _launch_service(db_session_factory, provider)
    key = f"content-generation:{run.id}"; record = MissionRepository(db_session).create(mission_id="existing", name="ContentGeneration", objective="generate and evaluate content brief", workflow_name="content_generate", input_data={"content_generation_run_id": run.id}, idempotency_key=key)
    result = launcher.launch(run.id)
    assert result.mission_id == record.id and result.mission_status == "CREATED" and manager.executor.engine.calls == 0 and provider.calls == 0
    assert db_session.query(MissionRecord).count() == 1 and db_session.query(Execution).count() == 0


def test_retryable_timeout_hands_off_to_frozen_mission_retry_stack(db_session, db_session_factory):
    run = _ready_run(db_session); provider = FakeProvider(ProviderGenerationResult(False, failure=ProviderFailure(ProviderFailureCategory.TIMEOUT, "safe timeout"))); launcher, _ = _launch_service(db_session_factory, provider)
    result = launcher.launch(run.id); mission, executions, worker = _durable(db_session, result.mission_id)
    refreshed = db_session.get(ContentGenerationRun, run.id)
    assert result.mission_status == mission.status == "RETRY_WAIT" and result.result_success is None
    assert len(executions) == 1 and executions[0].status == "QUEUED" and executions[0].failure_type == "TIMEOUT"
    assert refreshed.status == "RETRY_WAIT" and provider.calls == 1
    assert worker.status == WorkerStatus.BUSY.value and worker.current_mission_id == mission.id and worker.missions_completed == 0
    assert launcher.launch(run.id).mission_id == mission.id and db_session.query(Execution).count() == 1 and provider.calls == 1


def test_permanent_provider_failure_is_terminal_and_releases_worker_once(db_session, db_session_factory):
    run = _ready_run(db_session); provider = FakeProvider(ProviderGenerationResult(False, failure=ProviderFailure(ProviderFailureCategory.AUTHENTICATION, "secret must not leak"))); launcher, _ = _launch_service(db_session_factory, provider)
    result = launcher.launch(run.id); mission, executions, worker = _durable(db_session, result.mission_id)
    assert result.mission_status == mission.status == "FAILED" and result.result_success is False and "secret" not in result.result_error
    assert len(executions) == 1 and executions[0].status == "FAILED" and db_session.get(ContentGenerationRun, run.id).status == "FAILED"
    assert worker.status == WorkerStatus.ONLINE.value and worker.current_mission_id is None and worker.missions_completed == 1 and worker.missions_failed == 1
    assert launcher.launch(run.id).mission_id == mission.id and provider.calls == 1 and db_session.query(Execution).count() == 1


def test_restart_like_durable_lookup_prevents_second_execution_or_provider_call(db_session, db_session_factory):
    run = _ready_run(db_session); provider = FakeProvider(_content()); first, _ = _launch_service(db_session_factory, provider)
    launched = first.launch(run.id)
    second, second_manager = _launch_service(db_session_factory, provider)
    repeated = second.launch(run.id)
    assert launched.mission_id == repeated.mission_id and second_manager.executor.engine.calls == 0 and provider.calls == 1
    assert db_session.query(MissionRecord).count() == 1 and db_session.query(Execution).count() == 1


def test_workflow_closes_its_own_session_and_does_not_resume_retry_wait(db_session, db_session_factory):
    run = _ready_run(db_session, status="RETRY_WAIT"); sessions = []
    class TrackedSession:
        def __init__(self): self.session = db_session_factory(); self.closed = False
        def close(self): self.closed = True; self.session.close()
        def __getattr__(self, name): return getattr(self.session, name)
    def factory():
        tracked = TrackedSession(); sessions.append(tracked); return tracked
    provider = FakeProvider(_content())
    result = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda db: ContentGenerationService(db, FakeFactory(provider))).execute({"content_generation_run_id": run.id})
    assert result.success is False and "coordinator-owned" in result.errors[0] and provider.calls == 0
    assert len(sessions) == 1 and sessions[0].closed is True
