"""Narrow, deterministic errors for distribution adapter selection."""

from app.distribution.contracts import DistributionFailureCategory


class DistributionAdapterError(ValueError):
    """Base error for safe adapter-registry failures."""


class DuplicateDistributionAdapterError(DistributionAdapterError):
    """Raised when a platform is registered more than once."""


class UnsupportedDistributionPlatformError(DistributionAdapterError):
    """Raised when no adapter is registered for a normalized platform."""

    category = DistributionFailureCategory.UNSUPPORTED_PLATFORM

    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(f"unsupported distribution platform: {platform}")
