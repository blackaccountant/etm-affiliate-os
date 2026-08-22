"""
AI Manager

Central entry point for all AI interactions.
"""

from app.ai.provider_factory import ProviderFactory
from app.ai.result import AIResult


class AIManager:
    """
    Central AI Manager.

    Responsible for routing requests to the configured AI provider.
    """

    def __init__(self, provider: str | None = None):
        self.provider = ProviderFactory.create(provider)

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> AIResult:
        """
        Generate an AI response.
        """

        return self.provider.generate(
            prompt=prompt,
            **kwargs,
        )

    def health_check(self) -> bool:
        """
        Check provider health.
        """

        return self.provider.health_check()

    @property
    def provider_name(self) -> str:
        """
        Return the current provider name.
        """

        return self.provider.provider_name