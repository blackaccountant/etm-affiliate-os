"""Isolated HTTP acceptance coverage for the frozen content Mission boundary."""

from datetime import datetime, timezone
import inspect
import socket

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import content as content_api
from app.api.content import router
from app.content_intelligence.generation_contracts import (
    GeneratedClaim,
    ProviderFailure,
    ProviderFailureCategory,
    ProviderGenerationResult,
    StructuredGeneratedContent,
)
from app.content_intelligence.generation_service import ContentGenerationService
from app.content_intelligence.repurposing_service import ContentRepurposingService
from app.dependencies import get_content_mission_manager, get_db
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
from app.schemas.content import ContentMissionLaunchResponse
from app.services.content_brief_service import ContentBriefService
from app.workflows.content.content_generation_workflow import ContentGenerationWorkflow
from app.workflows.content.content_repurposing_workflow import ContentRepurposingWorkflow
from app.workforce.manager import WorkforceManager


@pytest.fixture(autouse=True)
def isolation_sentinels(monkeypatch):
    """Focused API coverage uses only injected SQLite sessions and fakes."""
    import app.database.session as database_session
    from app.ai.content_generation.factory import ContentGenerationProviderFactory

    calls = []

    def forbidden(*args, **kwargs):
        calls.append("configured access")
        raise AssertionError("configured SessionLocal, engine, network, or provider must not be used")

    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            forbidden(*args, **kwargs)

    monkeypatch.setattr("app.dependencies.SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx, "get", forbidden)
    monkeypatch.setattr(ContentGenerationProviderFactory, "create", forbidden)
    yield
    assert calls == []


class Provider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def generate(self, *args):
        self.calls += 1
        return self.results.pop(0)


class Factory:
    def __init__(self, provider):
        self.provider = provider

    def create(self, name):
        assert name == "openai"
        return self.provider


class Engine:
    def __init__(self, generation_workflow, repurposing_workflow):
        self.generation_workflow = generation_workflow
        self.repurposing_workflow = repurposing_workflow
        self.calls = 0

    def run(self, workflow_name, payload):
        self.calls += 1
        if workflow_name == "content_generate":
            return self.generation_workflow.execute(payload)
        assert workflow_name == "content_repurpose"
        return self.repurposing_workflow.execute(payload)


def success(body="The program pays 20% commission."):
    return ProviderGenerationResult(
        True,
        StructuredGeneratedContent(
            "Grounded title",
            "Grounded hook",
            body,
            "CHECK_DETAILS",
            "This contains affiliate links and may earn a commission.",
            (GeneratedClaim("Program pays 20%", ("evidence",)),),
        ),
    )


def failure(category=ProviderFailureCategory.TIMEOUT):
    return ProviderGenerationResult(False, failure=ProviderFailure(category, "safe provider failure"))


def ready_runs(db):
    now = datetime.now(timezone.utc)
    discovery = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="PERCENT", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    evidence = EvidenceObservation(id="evidence", candidate_id="candidate", claim_type="commission_percent", observed_value=20, source_url="https://example.com", source_type="official", excerpt="20% commission", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    source_generation = ContentGenerationRun(id="source-generation", content_brief_id="brief", idempotency_key="source-generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    db.add_all([discovery, candidate, brief, evidence, source_generation])
    db.flush()
    source = GeneratedContentArtifact(id="source", generation_run_id="source-generation", content_brief_id="brief", content_type="ARTICLE", title="Source", hook="Source hook", body="The program pays 20% commission.", call_to_action="CHECK_DETAILS", affiliate_disclosure="This contains affiliate links and may earn a commission.", claims=[{"text": "Program pays 20%", "source_evidence_ids": ["evidence"]}], status="GENERATED", created_at=now, updated_at=now)
    db.add(source)
    db.flush()
    db.add(ContentEvaluation(id="source-evaluation", artifact_id="source", content_brief_id="brief", generation_run_id="source-generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now))
    db.add(ContentBriefEvidence(id="link", content_brief_id="brief", evidence_observation_id="evidence", usage_role="ECONOMICS", created_at=now))
    db.commit()
    generation = ContentBriefService(db).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": 0.2, "max_output_tokens": 1200})
    repurpose_generation = ContentBriefService(db).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": 0.4, "max_output_tokens": 321, "operation": "repurpose", "source_artifact_id": "source", "source_evaluation_id": "source-evaluation", "target_content_type": "SOCIAL_POST", "channel_intent": "SOCIAL"})
    repurposing = ContentRepurposingRun(source_artifact_id="source", source_evaluation_id="source-evaluation", generation_run_id=repurpose_generation.id, target_content_type="SOCIAL_POST", channel_intent="SOCIAL", status="CREATED")
    db.add(repurposing)
    db.commit()
    return generation, repurposing


def manager(factory, generation_provider, repurposing_provider, *, workers=True):
    workforce = WorkforceManager(load_defaults=workers)
    generation = ContentGenerationWorkflow(session_factory=factory, generation_service_factory=lambda db: ContentGenerationService(db, Factory(generation_provider)))
    repurposing = ContentRepurposingWorkflow(session_factory=factory, repurposing_service_factory=lambda db: ContentRepurposingService(db, Factory(repurposing_provider)))
    result = MissionManager(workforce=workforce, session_factory=factory)
    result.executor.engine = Engine(generation, repurposing)
    return result


def client(factory, mission_manager):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_content_mission_manager] = lambda: mission_manager
    return TestClient(app, raise_server_exceptions=True)


def test_openapi_has_content_tag_and_exactly_the_six_audited_routes():
    app = FastAPI()
    app.include_router(router)
    document = app.openapi()
    assert {"/content/generation-runs/{content_generation_run_id}/launch", "/content/repurposing-runs/{content_repurposing_run_id}/launch", "/content/missions/{mission_id}", "/content/generation-runs/{run_id}", "/content/repurposing-runs/{run_id}", "/content/artifacts/{artifact_id}"} == set(document["paths"])
    assert document["paths"]["/content/generation-runs/{content_generation_run_id}/launch"]["post"]["tags"] == ["Content"]
    from app.main import app as main_app
    assert sum(getattr(route, "path", None) == "/content/generation-runs/{content_generation_run_id}/launch" for route in main_app.routes) == 1


@pytest.mark.parametrize("body,decision", [("The program pays 20% commission.", "APPROVED"), ("A customer says it is helpful.", "REJECTED")])
def test_generation_launch_is_durable_idempotent_and_editorial_results_are_technical_success(db_session, db_session_factory, body, decision):
    generation, _ = ready_runs(db_session)
    provider = Provider([success(body)])
    api = client(db_session_factory, manager(db_session_factory, provider, Provider([success()])))
    first = api.post(f"/content/generation-runs/{generation.id}/launch")
    second = api.post(f"/content/generation-runs/{generation.id}/launch")
    assert first.status_code == second.status_code == 200
    payload = first.json()
    assert set(payload) == set(ContentMissionLaunchResponse.model_fields)
    assert payload["content_generation_run_id"] == generation.id and payload["content_repurposing_run_id"] is None
    assert payload["mission_id"] == second.json()["mission_id"] and payload["result_success"] is True
    assert payload["result_data"]["content_generation_run_id"] == generation.id
    assert payload["result_data"]["evaluation_decision"] == decision
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 1 and provider.calls == 1


def test_generation_waiting_and_retry_wait_are_stable_mission_states(db_session, db_session_factory):
    generation, _ = ready_runs(db_session)
    waiting_provider = Provider([success()])
    waiting = client(db_session_factory, manager(db_session_factory, waiting_provider, Provider([success()]), workers=False)).post(f"/content/generation-runs/{generation.id}/launch")
    assert waiting.status_code == 200 and waiting.json()["mission_status"] == "WAITING_FOR_WORKER" and waiting.json()["result_success"] is None and waiting_provider.calls == 0
    retry_generation = ContentBriefService(db_session).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": 0.3, "max_output_tokens": 1200})
    retry = client(db_session_factory, manager(db_session_factory, Provider([failure()]), Provider([success()]))).post(f"/content/generation-runs/{retry_generation.id}/launch")
    assert retry.status_code == 200 and retry.json()["mission_status"] == "RETRY_WAIT" and retry.json()["result_success"] is None


@pytest.mark.parametrize("path", ["/content/generation-runs/missing/launch", "/content/repurposing-runs/missing/launch"])
def test_launch_missing_run_is_not_found(db_session_factory, path):
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), Provider([success()])))
    assert api.post(path).status_code == 404


def test_invalid_fresh_run_state_conflicts_only_without_a_mission(db_session, db_session_factory):
    generation, repurposing = ready_runs(db_session)
    generation.status = repurposing.status = "RUNNING"
    db_session.commit()
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), Provider([success()])))
    assert api.post(f"/content/generation-runs/{generation.id}/launch").status_code == 409
    assert api.post(f"/content/repurposing-runs/{repurposing.id}/launch").status_code == 409
    assert db_session.query(MissionRecord).count() == 0


@pytest.mark.parametrize("body,decision", [("The program pays 20% commission.", "APPROVED"), ("A customer says it is helpful.", "REJECTED")])
def test_repurposing_launch_is_durable_idempotent_and_preserves_editorial_success(db_session, db_session_factory, body, decision):
    _, repurposing = ready_runs(db_session)
    provider = Provider([success(body)])
    api = client(db_session_factory, manager(db_session_factory, Provider([success()]), provider))
    first = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    second = api.post(f"/content/repurposing-runs/{repurposing.id}/launch")
    assert first.status_code == second.status_code == 200
    assert first.json()["content_repurposing_run_id"] == repurposing.id and first.json()["mission_id"] == second.json()["mission_id"]
    assert first.json()["result_success"] is True and first.json()["result_data"]["evaluation_decision"] == decision
    assert db_session.query(MissionRecord).count() == db_session.query(Execution).count() == 1 and provider.calls == 1


def test_repurposing_waiting_and_retry_wait_are_stable_mission_states(db_session, db_session_factory):
    _, repurposing = ready_runs(db_session)
    waiting_provider = Provider([success()])
    waiting = client(db_session_factory, manager(db_session_factory, Provider([success()]), waiting_provider, workers=False)).post(f"/content/repurposing-runs/{repurposing.id}/launch")
    assert waiting.status_code == 200 and waiting.json()["mission_status"] == "WAITING_FOR_WORKER" and waiting_provider.calls == 0
    retry_generation = ContentBriefService(db_session).create_generation_run(content_brief_id="brief", provider="openai", model="fake", prompt_version="v1", generation_parameters={"temperature": 0.5, "max_output_tokens": 321, "operation": "repurpose", "source_artifact_id": "source", "source_evaluation_id": "source-evaluation", "target_content_type": "SOCIAL_POST", "channel_intent": "SOCIAL"})
    retry_repurposing = ContentRepurposingRun(source_artifact_id="source", source_evaluation_id="source-evaluation", generation_run_id=retry_generation.id, target_content_type="SOCIAL_POST", channel_intent="SOCIAL", status="CREATED")
    db_session.add(retry_repurposing)
    db_session.commit()
    retry = client(db_session_factory, manager(db_session_factory, Provider([success()]), Provider([failure()]))).post(f"/content/repurposing-runs/{retry_repurposing.id}/launch")
    assert retry.status_code == 200 and retry.json()["mission_status"] == "RETRY_WAIT" and retry.json()["result_success"] is None


def test_read_endpoints_are_safe_read_only_and_not_found_when_absent(db_session, db_session_factory):
    generation, repurposing = ready_runs(db_session)
    generation_provider = Provider([success()])
    api = client(db_session_factory, manager(db_session_factory, generation_provider, Provider([success()])))
    launched = api.post(f"/content/generation-runs/{generation.id}/launch").json()
    artifact_id = launched["result_data"]["artifact_id"]
    assert api.get(f"/content/missions/{launched['mission_id']}").status_code == 200
    assert api.get(f"/content/generation-runs/{generation.id}").json()["id"] == generation.id
    assert api.get(f"/content/repurposing-runs/{repurposing.id}").json()["id"] == repurposing.id
    artifact = api.get(f"/content/artifacts/{artifact_id}")
    assert artifact.status_code == 200 and artifact.json()["body"] == "The program pays 20% commission."
    assert generation_provider.calls == 1
    for path in ["/content/missions/missing", "/content/generation-runs/missing", "/content/repurposing-runs/missing", "/content/artifacts/missing"]:
        assert api.get(path).status_code == 404
    assert generation_provider.calls == 1


def test_router_has_no_direct_content_service_or_evaluator_bypass_and_no_secret_response(db_session, db_session_factory):
    source = inspect.getsource(content_api)
    assert "ContentGenerationService" not in source and "ContentRepurposingService" not in source and "ContentEvaluator" not in source
    generation, _ = ready_runs(db_session)
    response = client(db_session_factory, manager(db_session_factory, Provider([success()]), Provider([success()]))).post(f"/content/generation-runs/{generation.id}/launch")
    rendered = response.text.lower()
    assert response.status_code == 200
    for forbidden in ("database_url", "password", "api_key", "traceback", "postgresql://"):
        assert forbidden not in rendered
