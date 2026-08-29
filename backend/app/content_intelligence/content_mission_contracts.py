"""JSON-safe contracts shared by future content mission workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.content_intelligence.evaluation_contracts import EvaluationDecision


_RETRY_METADATA = {"mission_id", "execution_id", "worker_name", "retry_count", "max_retries", "failure_type"}
_DECISIONS = {item.value for item in EvaluationDecision}

CONTENT_GENERATION_MISSION_NAME = "ContentGeneration"
CONTENT_REPURPOSING_MISSION_NAME = "ContentRepurposing"
CONTENT_GENERATION_WORKFLOW = "content_generate"
CONTENT_REPURPOSING_WORKFLOW = "content_repurpose"
CONTENT_GENERATION_CAPABILITY = "content_generation"


def _required_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _payload(payload: object, field_name: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError("workflow payload is required")
    unknown = set(payload).difference({field_name} | _RETRY_METADATA)
    if unknown:
        raise ValueError("workflow payload contains unsupported runtime data")
    return _required_id(payload.get(field_name), field_name)


def content_generation_mission_idempotency_key(content_generation_run_id: object) -> str:
    return f"content-generation:{_required_id(content_generation_run_id, 'content_generation_run_id')}"


def content_repurposing_mission_idempotency_key(content_repurposing_run_id: object) -> str:
    return f"content-repurposing:{_required_id(content_repurposing_run_id, 'content_repurposing_run_id')}"


@dataclass(frozen=True)
class ContentGenerationWorkflowPayload:
    content_generation_run_id: str

    def __post_init__(self):
        object.__setattr__(self, "content_generation_run_id", _required_id(self.content_generation_run_id, "content_generation_run_id"))

    @classmethod
    def from_payload(cls, payload: object) -> "ContentGenerationWorkflowPayload":
        return cls(content_generation_run_id=_payload(payload, "content_generation_run_id"))

    def to_dict(self) -> dict[str, str]:
        return {"content_generation_run_id": self.content_generation_run_id}


@dataclass(frozen=True)
class ContentRepurposingWorkflowPayload:
    content_repurposing_run_id: str

    def __post_init__(self):
        object.__setattr__(self, "content_repurposing_run_id", _required_id(self.content_repurposing_run_id, "content_repurposing_run_id"))

    @classmethod
    def from_payload(cls, payload: object) -> "ContentRepurposingWorkflowPayload":
        return cls(content_repurposing_run_id=_payload(payload, "content_repurposing_run_id"))

    def to_dict(self) -> dict[str, str]:
        return {"content_repurposing_run_id": self.content_repurposing_run_id}


@dataclass(frozen=True)
class ContentGenerationWorkflowResult:
    content_brief_id: str
    content_generation_run_id: str
    artifact_id: str
    evaluation_id: str
    evaluation_decision: str

    def __post_init__(self):
        for name in ("content_brief_id", "content_generation_run_id", "artifact_id", "evaluation_id"):
            object.__setattr__(self, name, _required_id(getattr(self, name), name))
        if self.evaluation_decision not in _DECISIONS:
            raise ValueError("evaluation_decision is invalid")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ContentRepurposingWorkflowResult:
    source_artifact_id: str
    content_repurposing_run_id: str
    content_generation_run_id: str
    result_artifact_id: str
    evaluation_id: str
    evaluation_decision: str

    def __post_init__(self):
        for name in ("source_artifact_id", "content_repurposing_run_id", "content_generation_run_id", "result_artifact_id", "evaluation_id"):
            object.__setattr__(self, name, _required_id(getattr(self, name), name))
        if self.evaluation_decision not in _DECISIONS:
            raise ValueError("evaluation_decision is invalid")

    def to_dict(self) -> dict:
        return asdict(self)
