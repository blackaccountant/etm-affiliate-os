"""
AI Provider Factory

Production AI provider factory.

ETM Affiliate OS uses OpenAI as its production AI provider.
Local AI providers are not supported in production.
"""

from app.ai.providers.base_provider import BaseProvider
from app.ai.providers.openai_provider import OpenAIProvider


class ProviderFactory:
    """
    Factory for production AI providers.
    """

    _providers = {
        "openai": OpenAIProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str | None = None,
    ) -> BaseProvider:
        """
        Create the production AI provider.
        """

        provider_name = (
            provider or "openai"
        ).lower()

        provider_class = cls._providers.get(provider_name)

        if provider_class is None:
            raise ValueError(
                f"Unsupported AI provider: {provider_name}. "
                f"Supported providers: {list(cls._providers.keys())}"
            )

        return provider_class()

    @classmethod
    def available_providers(cls) -> list[str]:
        """
        Return available production providers.
        """
        return list(cls._providers.keys())