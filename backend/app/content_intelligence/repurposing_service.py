"""Grounded, idempotent transformation of an approved content artifact."""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass

from sqlalchemy.orm import Session

from app.ai.content_generation.factory import ContentGenerationProviderFactory
from app.content_intelligence.content_evaluator import ContentEvaluator
from app.content_intelligence.contracts import ContentType
from app.content_intelligence.evaluation_contracts import EVALUATOR_VERSION, POLICY_VERSION
from app.content_intelligence.generation_contracts import ProviderFailure, ProviderFailureCategory
from app.content_intelligence.prompt_builder import OUTPUT_SCHEMA
from app.content_intelligence.repurposing_contracts import ContentRepurposingResult
from app.content_intelligence.repurposing_prompt_builder import GroundedRepurposingPromptBuilder
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.discovery import EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.repositories.content_repurposing_run_repository import ContentRepurposingRunRepository
from app.repositories.generated_content_artifact_repository import GeneratedContentArtifactRepository
from app.services.content_brief_service import ContentBriefService


class GroundedRepurposingValidator:
    _forbidden = re.compile(r"\b(discount|limited[ -]?time|scarcity|guaranteed (income|earnings|results?)|testimonial|free trial|price|pricing|product feature|capability)\b", re.I)

    def validate(self, brief, content, whitelist: set[str], observations: dict[str, EvidenceObservation]) -> None:
        for field in (content.title, content.hook, content.body, content.cta, content.disclosure):
            if not isinstance(field, str) or not field.strip():
                raise ValueError("repurposed output is missing a required field")
        if content.cta != brief.call_to_action:
            raise ValueError("repurposed CTA does not preserve the brief CTA")
        disclosure = (content.disclosure + " " + content.body).lower()
        if "affiliate" not in disclosure or not ("link" in disclosure or "commission" in disclosure):
            raise ValueError("repurposed output is missing substantive affiliate disclosure")
        if self._forbidden.search(" ".join((content.title, content.hook, content.body, content.cta))):
            raise ValueError("repurposed output contains an unsupported claim")
        if not isinstance(content.claims, (tuple, list)):
            raise ValueError("repurposed claims must be a collection")
        for claim in content.claims:
            if not claim.text.strip() or not claim.source_evidence_ids:
                raise ValueError("repurposed factual claims require evidence IDs")
            if not set(claim.source_evidence_ids).issubset(whitelist):
                raise ValueError("repurposed claim evidence is outside the approved source whitelist")
        values = {row.claim_type: row.observed_value for row in observations.values()}
        text = " ".join((content.title, content.hook, content.body, content.cta))
        for value in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
            if "commission_percent" not in values or float(value) != float(values["commission_percent"]):
                raise ValueError("repurposed commission conflicts with approved evidence")
        for value in re.findall(r"(\d+)[- ]day cookie", text, re.I):
            if "cookie_days" not in values or int(value) != int(values["cookie_days"]):
                raise ValueError("repurposed cookie duration conflicts with approved evidence")


class ContentRepurposingService:
    _reserved = {"operation", "source_artifact_id", "source_evaluation_id", "target_content_type", "channel_intent"}

    def __init__(self, db: Session, provider_factory=ContentGenerationProviderFactory, prompt_builder=None, validator=None, evaluator=None):
        self.db = db
        self.provider_factory = provider_factory
        self.prompt_builder = prompt_builder or GroundedRepurposingPromptBuilder()
        self.validator = validator or GroundedRepurposingValidator()
        self.evaluator = evaluator or ContentEvaluator(db)
        self.briefs = ContentBriefService(db)
        self.runs = ContentRepurposingRunRepository(db)
        self.artifacts = GeneratedContentArtifactRepository(db)

    @staticmethod
    def _parameters(value) -> dict:
        if is_dataclass(value):
            value = asdict(value)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("generation parameters must be a mapping or GenerationParameters")
        return dict(value)

    def _canonical_parameters(self, request) -> dict:
        caller = self._parameters(request.generation_parameters)
        if self._reserved.intersection(caller):
            raise ValueError("caller cannot override reserved repurposing parameters")
        return {
            **caller,
            "operation": "repurpose",
            "source_artifact_id": request.source_artifact_id,
            "source_evaluation_id": request.source_evaluation_id,
            "target_content_type": request.target_content_type,
            "channel_intent": request.channel_intent,
        }

    def _source(self, request):
        artifact = self.db.get(GeneratedContentArtifact, request.source_artifact_id)
        if artifact is None:
            raise ValueError("source artifact not found")
        if artifact.status != "GENERATED":
            raise ValueError("source artifact is not GENERATED")
        evaluation = self.db.get(ContentEvaluation, request.source_evaluation_id)
        if evaluation is None or evaluation.artifact_id != artifact.id:
            raise ValueError("source evaluation does not belong to source artifact")
        if evaluation.decision != "APPROVED":
            raise ValueError("source evaluation is not APPROVED")
        if evaluation.evaluator_version != EVALUATOR_VERSION or evaluation.policy_version != POLICY_VERSION:
            raise ValueError("source evaluation does not use the current evaluation contract")
        brief = self.db.get(ContentBrief, artifact.content_brief_id)
        if brief is None:
            raise ValueError("source content brief not found")
        return artifact, evaluation, brief

    def _whitelist(self, artifact, brief) -> tuple[set[str], dict[str, EvidenceObservation]]:
        source_ids = {evidence_id for claim in (artifact.claims or []) for evidence_id in claim.get("source_evidence_ids", [])}
        links = self.db.query(ContentBriefEvidence).filter_by(content_brief_id=brief.id).all()
        linked_ids = {link.evidence_observation_id for link in links}
        allowed = source_ids.intersection(linked_ids)
        observations = {row.id: row for row in self.db.query(EvidenceObservation).filter(EvidenceObservation.id.in_(allowed)).all()} if allowed else {}
        if any(observations.get(evidence_id) is None or observations[evidence_id].candidate_id != brief.discovery_candidate_id for evidence_id in allowed):
            raise ValueError("source evidence whitelist contains cross-candidate evidence")
        return allowed, observations

    def _result(self, row, evaluation=None, failure=None):
        return ContentRepurposingResult(row.id, row.generation_run_id, row.result_artifact_id, evaluation.id if evaluation else None, row.status, evaluation.decision if evaluation else None, failure)

    def repurpose(self, request) -> ContentRepurposingResult:
        if request.target_content_type not in {item.value for item in ContentType}:
            raise ValueError("unsupported target content type")
        if not isinstance(request.channel_intent, str) or not request.channel_intent.strip():
            raise ValueError("channel intent is required")
        artifact, evaluation, brief = self._source(request)
        whitelist, observations = self._whitelist(artifact, brief)
        parameters = self._canonical_parameters(request)
        generation_run = self.briefs.create_generation_run(content_brief_id=brief.id, provider=request.provider, model=request.model, prompt_version=request.prompt_version, generation_parameters=parameters)
        row = self.runs.get_by_generation_run_id(generation_run.id)
        if row is None:
            row = self.runs.create(source_artifact_id=artifact.id, source_evaluation_id=evaluation.id, generation_run_id=generation_run.id, target_content_type=request.target_content_type, channel_intent=request.channel_intent, status="CREATED")
            self.db.commit()
            self.db.refresh(row)
        if row.status == "COMPLETED":
            result_evaluation = self.evaluator.repo.get_by_identity(row.result_artifact_id, EVALUATOR_VERSION, POLICY_VERSION) if row.result_artifact_id else None
            return self._result(row, result_evaluation)
        if row.status in {"RUNNING", "FAILED"}:
            return self._result(row)
        try:
            row.transition_to("RUNNING")
            generation_run.transition_to("RUNNING")
            self.db.commit()
            prompt = self.prompt_builder.build(artifact, whitelist, request)
            provider_result = self.provider_factory.create(request.provider).generate(prompt, OUTPUT_SCHEMA, request.generation_parameters, request.model)
            if not provider_result.success:
                return self._fail(row, generation_run, provider_result.failure or ProviderFailure(ProviderFailureCategory.UNKNOWN_PROVIDER_ERROR, "content provider failed"))
            self.validator.validate(brief, provider_result.content, whitelist, observations)
            result_artifact = self.artifacts.create(generation_run_id=generation_run.id, content_brief_id=brief.id, content_type=request.target_content_type, title=provider_result.content.title, hook=provider_result.content.hook, body=provider_result.content.body, call_to_action=provider_result.content.cta, affiliate_disclosure=provider_result.content.disclosure, claims=[{"text": claim.text, "source_evidence_ids": list(claim.source_evidence_ids), "claim_kind": claim.claim_kind} for claim in provider_result.content.claims], status="GENERATED")
            row.result_artifact_id = result_artifact.id
            result_evaluation = self.evaluator.evaluate(result_artifact.id, EVALUATOR_VERSION, POLICY_VERSION)
            row.transition_to("COMPLETED")
            generation_run.transition_to("COMPLETED")
            self.db.commit()
            return self._result(row, self.evaluator.repo.get_by_id(result_evaluation.evaluation_id))
        except Exception:
            return self._fail(row, generation_run, ProviderFailure(ProviderFailureCategory.MALFORMED_OUTPUT, "Repurposed content failed structural validation"))

    def _fail(self, row, generation_run, failure):
        row.error_summary = failure.safe_message
        if row.status == "RUNNING":
            row.transition_to("FAILED")
        generation_run.error_summary = failure.safe_message
        if generation_run.status == "RUNNING":
            generation_run.transition_to("FAILED")
        self.db.commit()
        return self._result(row, failure=failure)
