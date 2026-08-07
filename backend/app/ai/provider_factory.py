"""
AI Provider Factory

Creates AI provider instances based on configuration.
"""

from app.ai.config import ai_settings
from app.ai.providers.base_provider import BaseProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.openai_provider import OpenAIProvider


class ProviderFactory:
    """
    Factory for AI providers.
    """

    _providers = {
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
    }

    @classmethod
    def create(
        cls,
        provider: str | None = None,
    ) -> BaseProvider:
        """
        Create an AI provider.

        If provider is None, OpenAI is used by default.
        """

        provider_name = (
            provider or "openai"
        ).lower()

        provider_class = cls._providers.get(provider_name)

        if provider_class is None:
            raise ValueError(
                f"Unsupported AI provider: {provider_name}"
            )

        return provider_class()

    @classmethod
    def available_providers(cls) -> list[str]:
        """
        Return available providers.
        """
        return list(cls._providers.keys())