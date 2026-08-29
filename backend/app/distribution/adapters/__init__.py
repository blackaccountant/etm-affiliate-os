"""Provider-neutral distribution adapter boundary and registry."""

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry

__all__ = ["DistributionAdapter", "DistributionAdapterRegistry"]
