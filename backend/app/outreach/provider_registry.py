"""Explicit provider registration with no credential-bearing metadata."""

from __future__ import annotations

from collections.abc import Callable

from app.outreach.contracts import OutreachError, required_text
from app.outreach.provider_contracts import OutreachProvider, RESEND_PROVIDER_KEY


class OutreachProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], OutreachProvider]] = {}

    def register(self, provider_key: str, factory: Callable[[], OutreachProvider]) -> None:
        key = required_text(provider_key, "provider_key", 64).lower()
        if key in self._factories:
            raise OutreachError("DUPLICATE_PROVIDER", "outreach provider is already registered")
        if not callable(factory):
            raise OutreachError("INVALID_PROVIDER", "provider factory must be callable")
        self._factories[key] = factory

    def resolve(self, provider_key: str, channel: str) -> OutreachProvider:
        key = required_text(provider_key, "provider_key", 64).lower()
        factory = self._factories.get(key)
        if factory is None:
            raise OutreachError("UNKNOWN_PROVIDER", "outreach provider is not registered")
        provider = factory()
        capabilities = provider.capabilities
        if capabilities.provider_key != key or channel not in capabilities.channels:
            raise OutreachError("UNSUPPORTED_PROVIDER_CHANNEL", "provider does not support requested channel")
        return provider

    @property
    def registered_provider_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def build_default_provider_registry() -> OutreachProviderRegistry:
    from app.outreach.providers.resend import ResendEmailProvider

    registry = OutreachProviderRegistry()
    registry.register(RESEND_PROVIDER_KEY, ResendEmailProvider)
    return registry
