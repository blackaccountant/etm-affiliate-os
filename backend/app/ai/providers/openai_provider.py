"""
OpenAI Provider

Implementation of the BaseProvider using the
official OpenAI Python SDK.
"""

import time

from openai import OpenAI

from app.ai.config import ai_settings
from app.ai.providers.base_provider import BaseProvider
from app.ai.result import AIResult


class OpenAIProvider(BaseProvider):
    """
    OpenAI implementation of the BaseProvider.
    """

    @property
    def provider_name(self) -> str:
        return "OpenAI"

    @property
    def default_model(self) -> str:
        return ai_settings.openai_default_model

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> AIResult:
        """
        Generate a response using OpenAI.
        """

        model = kwargs.get("model") or self.default_model

        key = (ai_settings.openai_api_key or "").strip()

        print("\n========== OPENAI DEBUG ==========")
        print(f"Provider : {self.provider_name}")
        print(f"Model    : {model}")
        print(f"Key Head : {key[:20]}...")
        print(f"Key Tail : ...{key[-6:]}")
        print(f"Key Len  : {len(key)}")
        print("=================================\n")

        start = time.perf_counter()

        try:
            # Create a fresh client every request.
            # This guarantees we're using the current key from .env.
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
                prompt_tokens=getattr(usage, "input_tokens", 0),
                completion_tokens=getattr(usage, "output_tokens", 0),
                total_tokens=getattr(usage, "total_tokens", 0),
                execution_time=elapsed,
            )

        except Exception as exc:

            elapsed = time.perf_counter() - start

            print("\n========== OPENAI ERROR ==========")
            print(type(exc).__name__)
            print(exc)
            print("==================================\n")

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

        try:
            key = (ai_settings.openai_api_key or "").strip()

            client = OpenAI(
                api_key=key,
            )

            client.models.list()

            return True

        except Exception as exc:
            print("\n========== HEALTH CHECK ==========")
            print(exc)
            print("==================================\n")
            return False