"""Translate typed provider failures into safe frozen-retry classifier input."""

from app.content_intelligence.generation_contracts import ProviderFailure, ProviderFailureCategory


class ContentProviderFailureAdapter:
    _TEXT = {
        ProviderFailureCategory.TIMEOUT: "timeout",
        ProviderFailureCategory.RATE_LIMIT: "rate limit",
        ProviderFailureCategory.PROVIDER_UNAVAILABLE: "upstream unavailable",
        ProviderFailureCategory.AUTHENTICATION: "authentication error",
        ProviderFailureCategory.UNSUPPORTED_MODEL: "validation error: unsupported model",
        ProviderFailureCategory.CONTEXT_LENGTH: "validation error: context length",
        ProviderFailureCategory.INVALID_RESPONSE: "invalid provider response",
        ProviderFailureCategory.MALFORMED_OUTPUT: "validation error: malformed provider output",
        ProviderFailureCategory.MODEL_REFUSAL: "validation error: provider refusal",
        ProviderFailureCategory.UNKNOWN_PROVIDER_ERROR: "permanent provider error",
    }

    @classmethod
    def to_classifier_text(cls, failure: ProviderFailure | ProviderFailureCategory) -> str:
        category = failure.category if isinstance(failure, ProviderFailure) else failure
        try:
            return cls._TEXT[ProviderFailureCategory(category)]
        except (KeyError, ValueError):
            return "permanent provider error"
