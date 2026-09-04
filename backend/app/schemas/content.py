"""JSON-safe HTTP contracts for Mission-backed content operations."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ContentMissionLaunchResponse(_Response):
    content_generation_run_id: str | None = None
    content_repurposing_run_id: str | None = None
    mission_id: str
    mission_status: str
    workflow: str
    required_capability: str | None
    idempotency_key: str
    worker_name: str | None
    result_success: bool | None
    result_error: str | None
    result_data: dict[str, Any] | None


class ContentMissionResponse(_Response):
    id: str
    name: str
    objective: str
    workflow: str
    required_capability: str | None
    idempotency_key: str | None
    status: str
    worker_name: str | None
    result_success: bool | None
    result_error: str | None
    result_data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ContentGenerationRunResponse(_Response):
    id: str
    content_brief_id: str
    idempotency_key: str
    provider: str
    model: str
    prompt_version: str
    generation_parameters: dict[str, Any] | None
    status: str
    attempt_count: int
    result_summary: str | None
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ContentRepurposingRunResponse(_Response):
    id: str
    source_artifact_id: str
    source_evaluation_id: str
    generation_run_id: str
    result_artifact_id: str | None
    target_content_type: str
    channel_intent: str
    status: str
    error_summary: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GeneratedContentArtifactResponse(_Response):
    id: str
    generation_run_id: str
    content_brief_id: str
    content_type: str
    title: str
    hook: str
    body: str
    call_to_action: str
    affiliate_disclosure: str
    claims: list[dict[str, Any]]
    status: str
    created_at: datetime
    updated_at: datetime


class ContentBriefResponse(_Response):
    id: str
    discovery_run_id: str
    discovery_candidate_id: str
    content_type: str
    channel_intent: str
    objective: str
    audience_intent: str | None
    audience_problem: str | None
    angle: str | None
    call_to_action: str | None
    tone: str | None
    required_disclosure: str | None
    key_benefits: Any | None
    proof_points: Any | None
    target_keywords: Any | None
    constraints: Any | None
    idempotency_key: str
    status: str
    created_at: datetime
    updated_at: datetime


class ContentEvaluationResponse(_Response):
    id: str
    artifact_id: str
    content_brief_id: str
    generation_run_id: str
    factual_grounding_score: int
    offer_alignment_score: int
    intent_alignment_score: int
    clarity_score: int
    cta_score: int
    compliance_score: int
    overall_score: int
    decision: str
    approved: bool
    evaluator_version: str
    policy_version: str
    claim_results: Any
    compliance_flags: Any
    unsupported_claims: Any
    missing_evidence_ids: Any
    revision_reasons: Any
    rejection_reasons: Any
    created_at: datetime
    updated_at: datetime


class ContentOperationsSnapshotResponse(BaseModel):
    briefs: list[ContentBriefResponse]
    generation_runs: list[ContentGenerationRunResponse]
    artifacts: list[GeneratedContentArtifactResponse]
    evaluations: list[ContentEvaluationResponse]
    repurposing_runs: list[ContentRepurposingRunResponse]
