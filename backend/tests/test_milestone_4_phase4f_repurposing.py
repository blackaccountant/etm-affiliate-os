from datetime import datetime, timezone

import pytest

from app.content_intelligence.generation_contracts import GeneratedClaim, GenerationParameters, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.content_intelligence.repurposing_contracts import ContentRepurposingRequest
from app.content_intelligence.repurposing_service import ContentRepurposingService
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product


class FakeProvider:
    def __init__(self, result): self.result = result; self.calls = 0
    def generate(self, *args): self.calls += 1; return self.result


class FakeFactory:
    def __init__(self, provider): self.provider = provider
    def create(self, name):
        if name not in {"openai", "ollama"}: raise ValueError("Unsupported content generation provider")
        return self.provider


def _content(*, claims=(GeneratedClaim("Program pays 20%", ("commission",)),), body="The program pays 20% commission.", cta="CHECK_DETAILS", disclosure="This contains affiliate links and may earn a commission."):
    return ProviderGenerationResult(True, StructuredGeneratedContent("Variant", "A grounded hook", body, cta, disclosure, claims))


def _request(**changes):
    values = dict(source_artifact_id="source", source_evaluation_id="evaluation", target_content_type="SOCIAL_POST", channel_intent="SOCIAL", provider="openai", model="fake", prompt_version="v1", generation_parameters=GenerationParameters())
    values.update(changes)
    return ContentRepurposingRequest(**values)


def _evaluation(**changes):
    values = dict(id="evaluation", artifact_id="source", content_brief_id="brief", generation_run_id="source-gen", factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[])
    values.update(changes)
    return ContentEvaluation(**values)


def _source(db, *, evaluation=True, evidence_ids=("commission",), source_status="GENERATED"):
    now = datetime.now(timezone.utc)
    run = DiscoveryRun(id="discovery", input_type="URL", input_value="https://example.com", status="COMPLETED", idempotency_key="discovery", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
    candidate = DiscoveryCandidate(id="candidate", run_id="discovery", source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key="program", dedupe_key="dedupe", commission_model="PERCENT", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
    brief = ContentBrief(id="brief", discovery_run_id="discovery", discovery_candidate_id="candidate", content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key="brief", status="READY", created_at=now, updated_at=now)
    source_run = ContentGenerationRun(id="source-gen", content_brief_id="brief", idempotency_key="source-gen", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    commission = EvidenceObservation(id="commission", candidate_id="candidate", claim_type="commission_percent", observed_value=20, source_url="https://example.com", source_type="official", excerpt="20% commission", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    cookie = EvidenceObservation(id="cookie", candidate_id="candidate", claim_type="cookie_days", observed_value=30, source_url="https://example.com", source_type="official", excerpt="30-day cookie", extractor="test", extractor_version="1", confidence=95, observed_at=now, created_at=now)
    source = GeneratedContentArtifact(id="source", generation_run_id="source-gen", content_brief_id="brief", content_type="ARTICLE", title="Source", hook="Source hook", body="The program pays 20% commission with a 30-day cookie.", call_to_action="CHECK_DETAILS", affiliate_disclosure="This contains affiliate links and may earn a commission.", claims=[{"text": "Program pays 20%", "source_evidence_ids": list(evidence_ids)}], status=source_status, created_at=now, updated_at=now)
    db.add_all([run, candidate, brief, source_run, commission, cookie, source])
    db.flush()
    for evidence_id in ("commission", "cookie"):
        db.add(ContentBriefEvidence(id=f"link-{evidence_id}", content_brief_id="brief", evidence_observation_id=evidence_id, usage_role="ECONOMICS", created_at=now))
    if evaluation: db.add(_evaluation())
    db.commit()
    return source


def _service(db, provider): return ContentRepurposingService(db, FakeFactory(provider))


def test_current_approved_source_generates_lineage_and_its_own_evaluation(db_session):
    _source(db_session); provider = FakeProvider(_content()); result = _service(db_session, provider).repurpose(_request())
    row = db_session.get(ContentRepurposingRun, result.repurposing_run_id); artifact = db_session.get(GeneratedContentArtifact, result.artifact_id); evaluation = db_session.get(ContentEvaluation, result.evaluation_id)
    assert result.status == "COMPLETED" and provider.calls == 1
    assert row.source_artifact_id == "source" and row.source_evaluation_id == "evaluation" and row.result_artifact_id == artifact.id
    assert artifact.generation_run_id == row.generation_run_id and artifact.content_brief_id == "brief" and artifact.content_type == "SOCIAL_POST"
    assert evaluation.artifact_id == artifact.id and evaluation.id != "evaluation" and result.evaluation_decision == "APPROVED"
    assert db_session.query(Product).count() == db_session.query(AffiliateProgram).count() == db_session.query(AffiliateOpportunity).count() == db_session.query(AffiliateContentAsset).count() == 0


@pytest.mark.parametrize("evaluation_changes,error", [
    ({"decision": "REVISION_REQUIRED", "approved": False}, "not APPROVED"),
    ({"decision": "REJECTED", "approved": False}, "not APPROVED"),
    ({"artifact_id": "other"}, "does not belong"),
    ({"evaluator_version": "obsolete"}, "current evaluation contract"),
    ({"policy_version": "obsolete"}, "current evaluation contract"),
])
def test_only_current_approved_evaluation_authorizes_repurposing(db_session, evaluation_changes, error):
    _source(db_session); evaluation = db_session.get(ContentEvaluation, "evaluation")
    for key, value in evaluation_changes.items(): setattr(evaluation, key, value)
    db_session.commit()
    with pytest.raises(ValueError, match=error): _service(db_session, FakeProvider(_content())).repurpose(_request())


def test_unevaluated_source_is_rejected(db_session):
    _source(db_session, evaluation=False)
    with pytest.raises(ValueError, match="does not belong"): _service(db_session, FakeProvider(_content())).repurpose(_request())


@pytest.mark.parametrize("content,error", [
    (_content(claims=(GeneratedClaim("new", ("new-evidence",)),)), "whitelist"),
    (_content(disclosure=""), "disclosure"),
    (_content(cta="ACT_NOW"), "CTA"),
    (_content(body="It pays 30% commission."), "commission"),
    (_content(body="It includes a 60-day cookie."), "cookie"),
    (_content(body="A product feature is included."), "unsupported claim"),
])
def test_invalid_variant_is_rejected_before_artifact_persistence(db_session, content, error):
    _source(db_session); result = _service(db_session, FakeProvider(content)).repurpose(_request())
    assert result.status == "FAILED" and result.failure.category == ProviderFailureCategory.MALFORMED_OUTPUT
    assert db_session.query(GeneratedContentArtifact).count() == 1


def test_only_source_claim_and_brief_evidence_intersection_is_allowed(db_session):
    _source(db_session, evidence_ids=("commission",)); provider = FakeProvider(_content(claims=(GeneratedClaim("20 percent", ("cookie",)),), body="A valid neutral body."))
    result = _service(db_session, provider).repurpose(_request())
    assert result.status == "FAILED" and db_session.query(GeneratedContentArtifact).count() == 1


def test_identical_request_is_idempotent_and_distinct_target_and_intent_are_not(db_session):
    _source(db_session); provider = FakeProvider(_content()); service = _service(db_session, provider)
    first = service.repurpose(_request()); second = service.repurpose(_request())
    third = service.repurpose(_request(target_content_type="EMAIL")); fourth = service.repurpose(_request(channel_intent="NEWSLETTER"))
    assert first.artifact_id == second.artifact_id and provider.calls == 3
    assert len({first.generation_run_id, third.generation_run_id, fourth.generation_run_id}) == 3


@pytest.mark.parametrize("state", ["RUNNING", "FAILED"])
def test_existing_noncompleted_repurposing_run_does_not_call_provider(db_session, state):
    _source(db_session); provider = FakeProvider(_content()); service = _service(db_session, provider)
    request = _request(); source, evaluation, brief = service._source(request); parameters = service._canonical_parameters(request)
    generation = service.briefs.create_generation_run(content_brief_id=brief.id, provider=request.provider, model=request.model, prompt_version=request.prompt_version, generation_parameters=parameters)
    if state == "RUNNING": generation.transition_to("RUNNING")
    else: generation.transition_to("RUNNING"); generation.transition_to("FAILED")
    row = ContentRepurposingRun(source_artifact_id=source.id, source_evaluation_id=evaluation.id, generation_run_id=generation.id, target_content_type=request.target_content_type, channel_intent=request.channel_intent, status="CREATED")
    db_session.add(row); db_session.flush()
    if state == "RUNNING": row.transition_to("RUNNING")
    else: row.transition_to("RUNNING"); row.transition_to("FAILED")
    db_session.commit()
    result = service.repurpose(request)
    assert result.status == state and provider.calls == 0


def test_reserved_parameters_cannot_be_overridden_and_provider_failure_is_sanitized(db_session):
    _source(db_session)
    with pytest.raises(ValueError, match="reserved"):
        _service(db_session, FakeProvider(_content())).repurpose(_request(generation_parameters={"operation": "other"}))
    result = _service(db_session, FakeProvider(ProviderGenerationResult(False, failure=ProviderFailure(ProviderFailureCategory.TIMEOUT, "safe provider failure")))).repurpose(_request())
    row = db_session.get(ContentRepurposingRun, result.repurposing_run_id)
    assert result.status == "FAILED" and row.error_summary == "safe provider failure" and result.failure.retryable


def test_rejected_and_revision_variant_evaluations_complete_without_regeneration(db_session):
    _source(db_session)
    revision_provider = FakeProvider(_content(body="Act now to learn more."))
    revision_service = _service(db_session, revision_provider)
    revision = revision_service.repurpose(_request())
    rejected_provider = FakeProvider(_content(body="A customer says this is useful."))
    rejected_service = _service(db_session, rejected_provider)
    rejected = rejected_service.repurpose(_request(target_content_type="EMAIL"))
    assert revision.status == rejected.status == "COMPLETED"
    assert revision.evaluation_decision == "REVISION_REQUIRED" and rejected.evaluation_decision == "REJECTED"
    assert revision_service.repurpose(_request()).artifact_id == revision.artifact_id and revision_provider.calls == 1
    assert rejected_service.repurpose(_request(target_content_type="EMAIL")).artifact_id == rejected.artifact_id and rejected_provider.calls == 1
