from datetime import datetime, timezone
import socket

import pytest

from app.content_intelligence.content_mission_contracts import (CONTENT_GENERATION_CAPABILITY, CONTENT_GENERATION_MISSION_NAME, CONTENT_GENERATION_WORKFLOW, CONTENT_REPURPOSING_MISSION_NAME, CONTENT_REPURPOSING_WORKFLOW, ContentGenerationWorkflowPayload, ContentGenerationWorkflowResult, ContentRepurposingWorkflowPayload, ContentRepurposingWorkflowResult, content_generation_mission_idempotency_key, content_repurposing_mission_idempotency_key)
from app.content_intelligence.content_provider_failure_adapter import ContentProviderFailureAdapter
from app.content_intelligence.generation_contracts import GeneratedClaim, GenerationParameters, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.content_intelligence.repurposing_contracts import ContentRepurposingRequest
from app.content_intelligence.repurposing_service import ContentRepurposingService
from app.mission.status import MissionStatus
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.registry.default_workflows import create_workflow_registry
from app.retry.failure_classifier import FailureClassifier
from app.workforce.default_workers import create_default_workers


@pytest.fixture(autouse=True)
def forbid_configured_database(monkeypatch):
    """Focused contracts must never open the configured application database."""
    import app.database.session as database_session
    from app.ai.content_generation.factory import ContentGenerationProviderFactory
    import app.workflows.content.content_generation_workflow as generation_workflow
    import app.workflows.content.content_repurposing_workflow as repurposing_workflow

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
    repurposing_defaults = repurposing_workflow.ContentRepurposingWorkflow.__init__.__defaults__
    monkeypatch.setattr(database_session, "SessionLocal", forbidden_configured_session)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden_external_access)
    monkeypatch.setattr(socket.socket, "connect", forbidden_external_access)
    monkeypatch.setattr(ContentGenerationProviderFactory, "create", forbidden_external_access)
    monkeypatch.setattr(generation_workflow.ContentGenerationWorkflow.__init__, "__defaults__", (forbidden_configured_session, *defaults[1:]))
    monkeypatch.setattr(repurposing_workflow.ContentRepurposingWorkflow.__init__, "__defaults__", (forbidden_configured_session, *repurposing_defaults[1:]))
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


def _source(db):
    now = datetime.now(timezone.utc)
    run = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="PERCENT", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    source_run = ContentGenerationRun(id="source-generation", content_brief_id="brief", idempotency_key="source-generation", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    evidence = EvidenceObservation(id="evidence", candidate_id="candidate", claim_type="commission_percent", observed_value=20, source_url="https://example.com", source_type="official", excerpt="20% commission", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    source = GeneratedContentArtifact(id="source", generation_run_id="source-generation", content_brief_id="brief", content_type="ARTICLE", title="Source", hook="Source hook", body="The program pays 20% commission.", call_to_action="CHECK_DETAILS", affiliate_disclosure="This contains affiliate links and may earn a commission.", claims=[{"text": "Program pays 20%", "source_evidence_ids": ["evidence"]}], status="GENERATED", created_at=now, updated_at=now)
    evaluation = ContentEvaluation(id="source-evaluation", artifact_id="source", content_brief_id="brief", generation_run_id="source-generation", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)
    db.add_all([run, candidate, brief, source_run, evidence, source, evaluation]); db.flush()
    db.add(ContentBriefEvidence(id="link", content_brief_id="brief", evidence_observation_id="evidence", usage_role="ECONOMICS", created_at=now)); db.commit()


def _request(**changes):
    values = dict(source_artifact_id="source", source_evaluation_id="source-evaluation", target_content_type="SOCIAL_POST", channel_intent="SOCIAL", provider="openai", model="fake", prompt_version="v1", generation_parameters=GenerationParameters(temperature=.4, max_output_tokens=321), tone_constraints="  concise   friendly ", format_constraints="  one short paragraph  ")
    values.update(changes)
    return ContentRepurposingRequest(**values)


def _success():
    return ProviderGenerationResult(True, StructuredGeneratedContent("Title", "Hook", "The program pays 20% commission.", "CHECK_DETAILS", "This contains affiliate links and may earn a commission.", (GeneratedClaim("Program pays 20%", ("evidence",)),)))


def test_registry_adds_only_content_scaffolds_and_preserves_existing_workflows():
    registry = create_workflow_registry().all()
    assert {"affiliate_discovery", "product_discovery", "affiliate_discovery_run", "content_generate", "content_repurpose"} <= set(registry)
    assert list(registry).count("content_generate") == list(registry).count("content_repurpose") == 1
    assert all("content_evaluation" not in worker.capabilities for worker in create_default_workers())
    assert len(create_default_workers()) == 3


def test_future_mission_launch_contracts_are_explicit_and_id_only():
    assert (CONTENT_GENERATION_MISSION_NAME, CONTENT_GENERATION_WORKFLOW, CONTENT_GENERATION_CAPABILITY) == ("ContentGeneration", "content_generate", "content_generation")
    assert (CONTENT_REPURPOSING_MISSION_NAME, CONTENT_REPURPOSING_WORKFLOW) == ("ContentRepurposing", "content_repurpose")
    assert content_generation_mission_idempotency_key("generation") == "content-generation:generation"
    assert content_repurposing_mission_idempotency_key("repurposing") == "content-repurposing:repurposing"


def test_repurposing_workflow_is_registered_without_executing_default_session_or_provider():
    workflow = create_workflow_registry().get("content_repurpose")
    assert workflow.workflow_name == "content_repurpose"


def test_generation_workflow_is_registered_without_executing_default_session_or_provider():
    workflow = create_workflow_registry().get("content_generate")
    assert workflow.workflow_name == "content_generate"


@pytest.mark.parametrize("factory,payload", [(ContentGenerationWorkflowPayload, {"content_generation_run_id": object()}), (ContentRepurposingWorkflowPayload, {"content_repurposing_run_id": object()})])
def test_payload_contracts_reject_runtime_objects_and_extra_fields(factory, payload):
    with pytest.raises(ValueError): factory.from_payload(payload)
    valid = {"content_generation_run_id": "generation"} if factory is ContentGenerationWorkflowPayload else {"content_repurposing_run_id": "repurposing"}
    with pytest.raises(ValueError, match="runtime"): factory.from_payload({**valid, "session": "forbidden"})


def test_result_contracts_are_json_safe_and_editorial_rejection_is_technical_success_data():
    generation = ContentGenerationWorkflowResult("brief", "generation", "artifact", "evaluation", "REJECTED")
    repurposing = ContentRepurposingWorkflowResult("source", "repurposing", "generation", "result", "evaluation", "REVISION_REQUIRED")
    assert generation.to_dict()["evaluation_decision"] == "REJECTED"
    assert repurposing.to_dict()["content_repurposing_run_id"] == "repurposing"


@pytest.mark.parametrize("category,expected,retryable", [
    (ProviderFailureCategory.TIMEOUT, "timeout", True),
    (ProviderFailureCategory.RATE_LIMIT, "rate limit", True),
    (ProviderFailureCategory.PROVIDER_UNAVAILABLE, "upstream unavailable", True),
    (ProviderFailureCategory.AUTHENTICATION, "authentication error", False),
    (ProviderFailureCategory.UNSUPPORTED_MODEL, "validation error: unsupported model", False),
    (ProviderFailureCategory.CONTEXT_LENGTH, "validation error: context length", False),
    (ProviderFailureCategory.INVALID_RESPONSE, "invalid provider response", False),
    (ProviderFailureCategory.MALFORMED_OUTPUT, "validation error: malformed provider output", False),
    (ProviderFailureCategory.MODEL_REFUSAL, "validation error: provider refusal", False),
    (ProviderFailureCategory.UNKNOWN_PROVIDER_ERROR, "permanent provider error", False),
])
def test_provider_failure_adapter_is_safe_and_compatible_with_frozen_classifier(category, expected, retryable):
    raw = ProviderFailure(category, "credential=never-leak")
    text = ContentProviderFailureAdapter.to_classifier_text(raw)
    assert text == expected and "credential" not in text
    assert FailureClassifier().classify(text)["retryable"] is retryable


def test_editorial_constraints_persist_before_generation_and_survive_new_session(db_session, db_session_factory):
    _source(db_session); provider = FakeProvider(_success()); service = ContentRepurposingService(db_session, FakeFactory(provider))
    first = service.repurpose(_request()); second = service.repurpose(_request())
    row = db_session.get(ContentGenerationRun, first.generation_run_id)
    assert first.artifact_id == second.artifact_id and provider.calls == 1
    assert row.generation_parameters == {"temperature": .4, "max_output_tokens": 321, "operation": "repurpose", "source_artifact_id": "source", "source_evaluation_id": "source-evaluation", "target_content_type": "SOCIAL_POST", "channel_intent": "SOCIAL", "tone_constraints": "concise friendly", "format_constraints": "one short paragraph"}
    assert db_session.query(ContentGenerationRun).count() == 2
    db_session.close()
    reopened = db_session_factory()
    try:
        durable = reopened.get(ContentGenerationRun, first.generation_run_id)
        assert durable.generation_parameters["tone_constraints"] == "concise friendly"
        assert durable.generation_parameters["format_constraints"] == "one short paragraph"
        assert reopened.query(Product).count() == reopened.query(AffiliateProgram).count() == reopened.query(AffiliateOpportunity).count() == reopened.query(AffiliateContentAsset).count() == 0
    finally:
        reopened.close()


def test_editorial_constraint_inputs_are_validated_and_cannot_be_overridden(db_session):
    _source(db_session); service = ContentRepurposingService(db_session, FakeFactory(FakeProvider(_success())))
    with pytest.raises(ValueError, match="must not be blank"): service.repurpose(_request(tone_constraints="   "))
    with pytest.raises(ValueError, match="reserved"): service.repurpose(_request(generation_parameters={"tone_constraints": "forbidden"}))
