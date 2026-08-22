"""
Base AI Provider

Defines the interface implemented by production AI providers.
"""

from abc import ABC, abstractmethod

from app.ai.result import AIResult


class BaseProvider(ABC):
    """
    Abstract base class for AI providers.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Return the provider name.
        """
        pass

    @property
    @abstractmethod
    def default_model(self) -> str:
        """
        Return the default model used by the provider.
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