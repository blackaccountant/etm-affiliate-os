"""Explicit default composition for supported distribution adapters."""

from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.adapters.wordpress import WordPressDistributionAdapter


def create_default_distribution_adapter_registry() -> DistributionAdapterRegistry:
    registry = DistributionAdapterRegistry()
    registry.register(WordPressDistributionAdapter())
    return registry
