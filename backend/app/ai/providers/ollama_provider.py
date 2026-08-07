"""
Ollama Provider

Implementation of the BaseProvider using the
Ollama REST API.
"""

import time

import requests

from app.ai.config import ai_settings
from app.ai.providers.base_provider import BaseProvider
from app.ai.result import AIResult


class OllamaProvider(BaseProvider):
    """
    Ollama implementation of the BaseProvider.
    """

    @property
    def provider_name(self) -> str:
        return "Ollama"

    @property
    def default_model(self) -> str:
        return ai_settings.ollama_default_model

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> AIResult:
        """
        Generate a response using Ollama.
        """

        model = kwargs.get(
            "model",
            self.default_model,
        )

        start_time = time.perf_counter()

        try:
            response = requests.post(
                f"{ai_settings.ollama_base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120,
            )

            response.raise_for_status()

            result = response.json()

            execution_time = (
                time.perf_counter() - start_time
            )

            return AIResult(
                success=True,
                provider=self.provider_name,
                model=model,
                content=result.get("response", ""),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                execution_time=execution_time,
                metadata=result,
            )

        except Exception as exc:
            return AIResult(
                success=False,
                provider=self.provider_name,
                model=model,
                content="",
                error=str(exc),
            )

    def health_check(self) -> bool:
        """
        Verify Ollama connectivity.
        """

        try:
            response = requests.get(
                f"{ai_settings.ollama_base_url}/api/tags",
                timeout=10,
            )

            return response.status_code == 200

        except Exception:
            return False