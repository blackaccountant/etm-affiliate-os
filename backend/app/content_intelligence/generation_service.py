import re
from sqlalchemy.orm import Session

from app.ai.content_generation.factory import ContentGenerationProviderFactory
from app.content_intelligence.generation_contracts import ContentGenerationResult, ProviderFailure, ProviderFailureCategory
from app.content_intelligence.prompt_builder import GroundedContentPromptBuilder, OUTPUT_SCHEMA
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.repositories.content_generation_run_repository import ContentGenerationRunRepository
from app.repositories.generated_content_artifact_repository import GeneratedContentArtifactRepository
from app.services.content_brief_service import ContentBriefService

class GroundedGenerationValidator:
    _forbidden = re.compile(r"\b(discount|limited[ -]?time|scarcity|guaranteed (income|earnings|results)|testimonial)\b", re.I)
    def validate(self, brief, links, content):
        for field in (content.title, content.hook, content.body, content.cta, content.disclosure):
            if not str(field).strip(): raise ValueError("generated output is missing a required field")
        if content.cta != brief.call_to_action: raise ValueError("generated CTA does not match brief CTA")
        if self._forbidden.search(" ".join((content.title, content.hook, content.body))): raise ValueError("generated output contains a forbidden claim")
        allowed = {link.evidence_observation_id for link in links}
        for claim in content.claims:
            if not claim.text.strip() or not claim.source_evidence_ids: raise ValueError("factual claims require evidence IDs")
            if not set(claim.source_evidence_ids).issubset(allowed): raise ValueError("claim evidence does not belong to the content brief")

class ContentGenerationService:
    def __init__(self, db: Session, provider_factory=ContentGenerationProviderFactory, prompt_builder=None, validator=None):
        self.db=db; self.briefs=ContentBriefService(db); self.runs=ContentGenerationRunRepository(db); self.artifacts=GeneratedContentArtifactRepository(db); self.provider_factory=provider_factory; self.prompt_builder=prompt_builder or GroundedContentPromptBuilder(); self.validator=validator or GroundedGenerationValidator()
    def generate(self, request, *, defer_retryable_failure=False, retry_resume=False):
        brief=self.db.get(ContentBrief, request.content_brief_id)
        if brief is None: raise ValueError("content brief not found")
        if brief.status != "READY": raise ValueError("content brief is not READY")
        run=self.briefs.create_generation_run(content_brief_id=brief.id, provider=request.provider, model=request.model, prompt_version=request.prompt_version, generation_parameters={"temperature":request.generation_parameters.temperature,"max_output_tokens":request.generation_parameters.max_output_tokens})
        artifact=self.artifacts.get_by_generation_run_id(run.id)
        if run.status == "COMPLETED": return ContentGenerationResult(run.id, artifact.id if artifact else None, run.status)
        if run.status == "RETRY_WAIT" and retry_resume:
            run_id = run.id
            run = self.runs.claim_retry_resume(run.id)
            if run is None:
                return ContentGenerationResult(run_id, None, "RETRY_WAIT")
        elif run.status == "RETRY_WAIT": return ContentGenerationResult(run.id, None, run.status)
        if run.status != "CREATED" and not (retry_resume and run.status == "RUNNING"):
            return ContentGenerationResult(run.id, None, run.status)
        if run.status == "CREATED":
            run.transition_to("RUNNING")
            self.db.commit()
        links=self.db.query(ContentBriefEvidence).filter_by(content_brief_id=brief.id).all()
        try:
            prompt=self.prompt_builder.build(brief, links); result=self.provider_factory.create(request.provider).generate(prompt, OUTPUT_SCHEMA, request.generation_parameters, request.model)
            if not result.success: return self._fail(run, result.failure or ProviderFailure(ProviderFailureCategory.UNKNOWN_PROVIDER_ERROR, "content provider failed"), defer_retryable_failure=defer_retryable_failure)
            self.validator.validate(brief, links, result.content)
            artifact=self.artifacts.create(generation_run_id=run.id, content_brief_id=brief.id, content_type=brief.content_type, title=result.content.title, hook=result.content.hook, body=result.content.body, call_to_action=result.content.cta, affiliate_disclosure=result.content.disclosure, claims=[{"text":c.text,"source_evidence_ids":list(c.source_evidence_ids),"claim_kind":c.claim_kind} for c in result.content.claims], status="GENERATED")
            run.transition_to("COMPLETED"); self.db.commit(); self.db.refresh(artifact)
            return ContentGenerationResult(run.id, artifact.id, run.status)
        except Exception:
            return self._fail(run, ProviderFailure(ProviderFailureCategory.MALFORMED_OUTPUT, "Generated content failed structural validation"))
    def _fail(self, run, failure, *, defer_retryable_failure=False):
        run.error_summary=failure.safe_message
        run.transition_to("RETRY_WAIT" if defer_retryable_failure and failure.retryable else "FAILED")
        self.db.commit()
        return ContentGenerationResult(run.id, None, run.status, failure)
