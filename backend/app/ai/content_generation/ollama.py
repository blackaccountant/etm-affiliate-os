import json
import requests

from app.ai.content_generation.base import ContentGenerationProvider
from app.ai.content_generation.openai import _content, _failure
from app.content_intelligence.generation_contracts import ProviderFailure, ProviderFailureCategory, ProviderGenerationResult
from app.core.config import settings

class OllamaContentGenerationProvider(ContentGenerationProvider):
    def __init__(self, transport=None): self.transport = transport or requests.Session()
    def generate(self, prompt, output_schema, parameters, model):
        try:
            response = self.transport.post(settings.OLLAMA_BASE_URL.rstrip("/") + "/api/chat", json={"model": model or settings.OLLAMA_CONTENT_MODEL, "messages": [{"role":"user", "content":prompt.text}], "format": output_schema, "stream":False, "options":{"temperature":parameters.temperature}}, timeout=settings.OLLAMA_CONTENT_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json(); raw = payload.get("message", {}).get("content") or payload.get("response")
            return ProviderGenerationResult(success=True, content=_content(json.loads(raw)))
        except requests.Timeout:
            return ProviderGenerationResult(success=False, failure=ProviderFailure(ProviderFailureCategory.TIMEOUT, "Ollama content generation timed out"))
        except requests.ConnectionError:
            return ProviderGenerationResult(success=False, failure=ProviderFailure(ProviderFailureCategory.PROVIDER_UNAVAILABLE, "Ollama content provider is unavailable"))
        except Exception as exc:
            return ProviderGenerationResult(success=False, failure=_failure(exc))
