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
