from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderFailureCategory(str, Enum):
    TIMEOUT="TIMEOUT"; RATE_LIMIT="RATE_LIMIT"; PROVIDER_UNAVAILABLE="PROVIDER_UNAVAILABLE"; AUTHENTICATION="AUTHENTICATION"
    UNSUPPORTED_MODEL="UNSUPPORTED_MODEL"; CONTEXT_LENGTH="CONTEXT_LENGTH"; INVALID_RESPONSE="INVALID_RESPONSE"
    MALFORMED_OUTPUT="MALFORMED_OUTPUT"; MODEL_REFUSAL="MODEL_REFUSAL"; UNKNOWN_PROVIDER_ERROR="UNKNOWN_PROVIDER_ERROR"

@dataclass(frozen=True)
class ProviderFailure:
    category: ProviderFailureCategory; safe_message: str
    @property
    def retryable(self): return self.category in {ProviderFailureCategory.TIMEOUT, ProviderFailureCategory.RATE_LIMIT, ProviderFailureCategory.PROVIDER_UNAVAILABLE}

@dataclass(frozen=True)
class GenerationParameters:
    temperature: float = 0.2; max_output_tokens: int = 1200

@dataclass(frozen=True)
class ContentGenerationRequest:
    content_brief_id: str; provider: str; model: str; prompt_version: str
    generation_parameters: GenerationParameters = field(default_factory=GenerationParameters)

@dataclass(frozen=True)
class ContentGenerationPrompt:
    text: str; evidence_ids: tuple[str, ...]

@dataclass(frozen=True)
class GeneratedClaim:
    text: str; source_evidence_ids: tuple[str, ...]; claim_kind: str | None = None

@dataclass(frozen=True)
class StructuredGeneratedContent:
    title: str; hook: str; body: str; cta: str; disclosure: str; claims: tuple[GeneratedClaim, ...]

@dataclass(frozen=True)
class ProviderGenerationResult:
    success: bool; content: StructuredGeneratedContent | None = None; failure: ProviderFailure | None = None

@dataclass(frozen=True)
class ContentGenerationResult:
    generation_run_id: str; artifact_id: str | None; status: str; failure: ProviderFailure | None = None
