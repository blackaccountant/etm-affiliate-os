"""Deterministic registry for explicitly registered distribution adapters."""

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.contracts import normalize_platform
from app.distribution.exceptions import DuplicateDistributionAdapterError, UnsupportedDistributionPlatformError


class DistributionAdapterRegistry:
    """Select only explicit adapters; registry construction has no side effects."""

    def __init__(self) -> None:
        self._adapters: dict[str, DistributionAdapter] = {}

    def register(self, adapter: DistributionAdapter) -> None:
        platform = normalize_platform(adapter.metadata.platform)
        if platform in self._adapters:
            raise DuplicateDistributionAdapterError(f"distribution adapter already registered: {platform}")
        self._adapters[platform] = adapter

    def resolve(self, platform: object) -> DistributionAdapter:
        normalized = normalize_platform(platform)
        try:
            return self._adapters[normalized]
        except KeyError as exc:
            raise UnsupportedDistributionPlatformError(normalized) from exc

    @property
    def registered_platforms(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
