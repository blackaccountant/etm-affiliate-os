from datetime import datetime, timezone

import pytest

from app.content_intelligence.generation_contracts import (ContentGenerationRequest, GeneratedClaim, GenerationParameters, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent)
from app.content_intelligence.generation_service import ContentGenerationService
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product

class FakeProvider:
    def __init__(self, result): self.result=result; self.calls=0
    def generate(self, *args): self.calls += 1; return self.result
class FakeFactory:
    def __init__(self, provider): self.provider=provider
    def create(self, name):
        if name not in {"openai", "ollama"}: raise ValueError("Unsupported content generation provider")
        return self.provider

def _ready(db, *, status="READY"):
    now=datetime.now(timezone.utc)
    run=DiscoveryRun(id="run",input_type="URL",input_value="https://example.com",status="COMPLETED",idempotency_key="run",candidate_count=1,verified_count=1,selected_count=1,created_at=now,updated_at=now)
    candidate=DiscoveryCandidate(id="candidate",run_id="run",source_adapter="official",source_type="official",canonical_domain="example.com",program_identity_key="p",dedupe_key="d",commission_model="UNKNOWN",verification_status="VERIFIED",disposition="SELECTED",created_at=now,updated_at=now)
    brief=ContentBrief(id="brief",discovery_run_id="run",discovery_candidate_id="candidate",content_type="ARTICLE",channel_intent="SEO",objective="Grounded facts",call_to_action="CHECK_DETAILS",required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED",key_benefits=[],proof_points=[],target_keywords=[],constraints=["NO_UNSUPPORTED_CLAIMS"],idempotency_key="brief",status=status,created_at=now,updated_at=now)
    evidence=EvidenceObservation(id="evidence",candidate_id="candidate",claim_type="affiliate_program_exists",observed_value=True,source_url="https://example.com/affiliate",source_type="official",excerpt="Affiliate program",extractor="test",extractor_version="1",confidence=95,observed_at=now,created_at=now)
    db.add_all([run,candidate,brief,evidence]); db.flush(); db.add(ContentBriefEvidence(id="link",content_brief_id="brief",evidence_observation_id="evidence",usage_role="PRIMARY",created_at=now)); db.commit()
    return brief
def _request(): return ContentGenerationRequest("brief","openai","fake-model","v1",GenerationParameters())
def _success(): return ProviderGenerationResult(True, StructuredGeneratedContent("Title","Hook","Body","CHECK_DETAILS","AFFILIATE_DISCLOSURE_REQUIRED",(GeneratedClaim("Program exists",("evidence",)),)))

def test_ready_brief_generates_one_grounded_artifact_idempotently(db_session):
    _ready(db_session); provider=FakeProvider(_success()); service=ContentGenerationService(db_session, FakeFactory(provider))
    first=service.generate(_request()); second=service.generate(_request())
    assert first.status == "COMPLETED" and second.artifact_id == first.artifact_id and provider.calls == 1
    artifact=db_session.get(GeneratedContentArtifact, first.artifact_id)
    assert artifact.status == "GENERATED" and artifact.claims[0]["source_evidence_ids"] == ["evidence"]
    assert db_session.query(ContentGenerationRun).count() == 1 and db_session.query(GeneratedContentArtifact).count() == 1
    assert db_session.query(Product).count() == db_session.query(AffiliateProgram).count() == db_session.query(AffiliateOpportunity).count() == db_session.query(AffiliateContentAsset).count() == 0

@pytest.mark.parametrize("status", ["CREATED", "FAILED"])
def test_non_ready_brief_is_rejected(db_session, status):
    _ready(db_session,status=status)
    with pytest.raises(ValueError, match="not READY"): ContentGenerationService(db_session, FakeFactory(FakeProvider(_success()))).generate(_request())

@pytest.mark.parametrize("content", [
    StructuredGeneratedContent("","Hook","Body","CHECK_DETAILS","disc",()),
    StructuredGeneratedContent("Title","Hook","Body","BAD","disc",()),
    StructuredGeneratedContent("Title","Hook","Body","CHECK_DETAILS","",()),
    StructuredGeneratedContent("Title","Hook","Body","CHECK_DETAILS","disc",(GeneratedClaim("claim",()),)),
    StructuredGeneratedContent("Title","Hook","Body","CHECK_DETAILS","disc",(GeneratedClaim("claim",("unknown",)),)),
])
def test_invalid_structured_output_fails_without_artifact(db_session, content):
    _ready(db_session); provider=FakeProvider(ProviderGenerationResult(True,content)); result=ContentGenerationService(db_session, FakeFactory(provider)).generate(_request())
    assert result.status == "FAILED" and result.failure.category == ProviderFailureCategory.MALFORMED_OUTPUT and db_session.query(GeneratedContentArtifact).count() == 0

@pytest.mark.parametrize("category,retryable", [(ProviderFailureCategory.TIMEOUT,True),(ProviderFailureCategory.RATE_LIMIT,True),(ProviderFailureCategory.PROVIDER_UNAVAILABLE,True),(ProviderFailureCategory.AUTHENTICATION,False),(ProviderFailureCategory.UNSUPPORTED_MODEL,False)])
def test_provider_failure_is_sanitized_and_classified(db_session, category, retryable):
    _ready(db_session); result=ContentGenerationService(db_session, FakeFactory(FakeProvider(ProviderGenerationResult(False,failure=ProviderFailure(category,"safe failure"))))).generate(_request())
    run=db_session.get(ContentGenerationRun,result.generation_run_id)
    assert result.status == "FAILED" and result.failure.retryable is retryable and run.error_summary == "safe failure"

@pytest.mark.parametrize("state", ["RUNNING","FAILED","RETRY_WAIT"])
def test_nonfresh_run_never_calls_provider(db_session,state):
    _ready(db_session); provider=FakeProvider(_success()); service=ContentGenerationService(db_session,FakeFactory(provider))
    run=service.briefs.create_generation_run(content_brief_id="brief",provider="openai",model="fake-model",prompt_version="v1",generation_parameters={"temperature":.2,"max_output_tokens":1200})
    if state == "RUNNING": run.transition_to("RUNNING")
    elif state == "FAILED": run.transition_to("RUNNING"); run.transition_to("FAILED")
    else: run.transition_to("RUNNING"); run.transition_to("RETRY_WAIT")
    db_session.commit()
    assert service.generate(_request()).status == state and provider.calls == 0

def test_factory_unknown_provider_rejected():
    from app.ai.content_generation.factory import ContentGenerationProviderFactory
    with pytest.raises(ValueError): ContentGenerationProviderFactory.create("unknown")

def test_openai_adapter_normalizes_injected_response_without_network():
    from types import SimpleNamespace
    from app.ai.content_generation.openai import OpenAIContentGenerationProvider
    from app.content_intelligence.generation_contracts import ContentGenerationPrompt
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: SimpleNamespace(output_text='{"title":"Title","hook":"Hook","body":"Body","cta":"CHECK_DETAILS","disclosure":"disc","claims":[{"text":"fact","source_evidence_ids":["evidence"]}]}')))
    result = OpenAIContentGenerationProvider(client).generate(ContentGenerationPrompt("prompt", ("evidence",)), {}, GenerationParameters(), "model")
    assert result.success and result.content.claims[0].source_evidence_ids == ("evidence",)

def test_ollama_adapter_normalizes_injected_transport_without_network():
    from app.ai.content_generation.ollama import OllamaContentGenerationProvider
    from app.content_intelligence.generation_contracts import ContentGenerationPrompt
    response = type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"message":{"content":'{"title":"Title","hook":"Hook","body":"Body","cta":"CHECK_DETAILS","disclosure":"disc","claims":[{"text":"fact","source_evidence_ids":["evidence"]}]}'}}})()
    transport = type("Transport", (), {"post": lambda self, *args, **kwargs: response})()
    result = OllamaContentGenerationProvider(transport).generate(ContentGenerationPrompt("prompt", ("evidence",)), {}, GenerationParameters(), "model")
    assert result.success and result.content.title == "Title"
