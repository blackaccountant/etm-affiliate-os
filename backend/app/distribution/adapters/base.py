"""Provider-neutral adapter protocol; concrete platforms are intentionally deferred."""

from abc import ABC, abstractmethod

from app.distribution.contracts import (
    DistributionAdapterMetadata,
    DistributionPublishRequest,
    DistributionPublishResult,
    DistributionStatusRequest,
    DistributionStatusResult,
    DistributionValidationRequest,
    DistributionValidationResult,
)


class DistributionAdapter(ABC):
    """Pure boundary for future platform adapters, with no credential resolution."""

    @property
    @abstractmethod
    def metadata(self) -> DistributionAdapterMetadata:
        """Return immutable platform capabilities without making external calls."""

    @abstractmethod
    def validate_target(self, request: DistributionValidationRequest) -> DistributionValidationResult:
        """Validate a non-secret target using a future platform implementation."""

    @abstractmethod
    def publish(self, request: DistributionPublishRequest) -> DistributionPublishResult:
        """Publish already-prepared content using a future platform implementation."""

    def get_publish_status(self, request: DistributionStatusRequest) -> DistributionStatusResult:
        """Optionally reconcile a previous submission when metadata permits it."""
        raise NotImplementedError(f"{self.metadata.platform} does not support status lookup")
