"""Provider-neutral contracts for grounded content repurposing."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.content_intelligence.generation_contracts import GenerationParameters, ProviderFailure


class RepurposingStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ContentRepurposingRequest:
    source_artifact_id: str
    source_evaluation_id: str
    target_content_type: str
    channel_intent: str
    provider: str
    model: str
    prompt_version: str
    generation_parameters: GenerationParameters | dict[str, Any] = field(default_factory=GenerationParameters)
    tone_constraints: str | None = None
    format_constraints: str | None = None


@dataclass(frozen=True)
class ContentRepurposingResult:
    repurposing_run_id: str
    generation_run_id: str
    artifact_id: str | None
    evaluation_id: str | None
    status: str
    evaluation_decision: str | None = None
    failure: ProviderFailure | None = None
