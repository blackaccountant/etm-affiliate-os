"""Durable distribution contracts; platform execution is intentionally deferred."""

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.failure_adapter import DistributionFailureAdapter

__all__ = [
    "DistributionAdapter",
    "DistributionAdapterRegistry",
    "DistributionFailureAdapter",
]
