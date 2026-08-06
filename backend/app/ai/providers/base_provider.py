"""
Base AI Provider

Every AI provider (OpenAI, Ollama, Anthropic, Gemini, etc.)
must inherit from this class.

This guarantees that every provider exposes the same interface
to the AI Manager.
"""

from abc import ABC, abstractmethod

from app.ai.result import AIResult


class BaseProvider(ABC):
    """
    Abstract base class for all AI providers.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Return the provider name.

        Example:
            OpenAI
            Ollama
            Anthropic
        """
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """
        Return the default model used by this provider.
        """
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> AIResult:
        """
        Generate a response from the AI model.

        Returns:
            AIResult
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Verify the provider is available.

        Returns:
            True if healthy.
        """
        pass