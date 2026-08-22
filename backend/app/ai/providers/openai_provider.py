"""
OpenAI Provider

Production implementation of the BaseProvider using
the official OpenAI Python SDK.
"""

import time

from openai import OpenAI

from app.ai.providers.base_provider import BaseProvider
from app.ai.result import AIResult
from app.core.config import settings


class OpenAIProvider(BaseProvider):
    """
    OpenAI implementation of the BaseProvider.
    """

    @property
    def provider_name(self) -> str:
        return "OpenAI"

    @property
    def default_model(self) -> str:
        return settings.OPENAI_DEFAULT_MODEL

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> AIResult:
        """
        Generate a response using OpenAI.
        """

        model = kwargs.get("model") or self.default_model

        key = (settings.OPENAI_API_KEY or "").strip()

        if not key:
            return AIResult(
                success=False,
                provider=self.provider_name,
                model=model,
                content="",
                error="OPENAI_API_KEY is not configured.",
            )

        start = time.perf_counter()

        try:
            client = OpenAI(
                api_key=key,
            )

            response = client.responses.create(
                model=model,
                input=prompt,
            )

            elapsed = time.perf_counter() - start

            usage = getattr(response, "usage", None)

            return AIResult(
                success=True,
                provider=self.provider_name,
                model=model,
                content=response.output_text,
                prompt_tokens=getattr(
                    usage,
                    "input_tokens",
                    0,
                ),
                completion_tokens=getattr(
                    usage,
                    "output_tokens",
                    0,
                ),
                total_tokens=getattr(
                    usage,
                    "total_tokens",
                    0,
                ),
                execution_time=elapsed,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start

            return AIResult(
                success=False,
                provider=self.provider_name,
                model=model,
                content="",
                execution_time=elapsed,
                error=str(exc),
            )

    def health_check(self) -> bool:
        """
        Verify OpenAI connectivity.
        """

        key = (settings.OPENAI_API_KEY or "").strip()

        if not key:
            return False

        try:
            client = OpenAI(
                api_key=key,
            )

            client.models.list()

            return True

        except Exception:
            return False
