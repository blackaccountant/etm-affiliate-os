"""Translate normalized distribution failures into safe retry-classifier input."""

from app.distribution.contracts import DistributionFailureCategory


class DistributionFailureAdapter:
    """Never forwards raw provider exceptions into the mission retry classifier."""

    _TEXT = {
        DistributionFailureCategory.RATE_LIMIT: "rate limit",
        DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT: "timeout before submit",
        DistributionFailureCategory.PROVIDER_UNAVAILABLE: "upstream unavailable",
        DistributionFailureCategory.AUTHENTICATION: "authentication error",
        DistributionFailureCategory.PERMISSION_DENIED: "permission denied",
        DistributionFailureCategory.INVALID_CONTENT: "validation error: invalid content",
        DistributionFailureCategory.INVALID_DESTINATION: "validation error: invalid destination",
        DistributionFailureCategory.UNSUPPORTED_PLATFORM: "unsupported distribution platform",
        DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT: "external publish result requires reconciliation",
        DistributionFailureCategory.UNKNOWN_PERMANENT: "permanent distribution provider error",
    }

    @classmethod
    def to_classifier_text(cls, category: DistributionFailureCategory) -> str:
        try:
            return cls._TEXT[DistributionFailureCategory(category)]
        except (KeyError, ValueError):
            return "permanent distribution provider error"
