import json
from openai import OpenAI

from app.ai.content_generation.base import ContentGenerationProvider
from app.content_intelligence.generation_contracts import GeneratedClaim, ProviderFailure, ProviderFailureCategory, ProviderGenerationResult, StructuredGeneratedContent
from app.core.config import settings

class OpenAIContentGenerationProvider(ContentGenerationProvider):
    def __init__(self, client=None): self.client = client
    def generate(self, prompt, output_schema, parameters, model):
        try:
            client = self.client or OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_CONTENT_TIMEOUT_SECONDS)
            response = client.responses.create(model=model or settings.OPENAI_CONTENT_MODEL, input=prompt.text, text={"format": {"type": "json_schema", "name": "grounded_content", "schema": output_schema, "strict": True}}, max_output_tokens=parameters.max_output_tokens)
            return ProviderGenerationResult(success=True, content=_content(json.loads(response.output_text)))
        except Exception as exc:
            return ProviderGenerationResult(success=False, failure=_failure(exc))

def _content(value):
    return StructuredGeneratedContent(title=str(value.get("title", "")), hook=str(value.get("hook", "")), body=str(value.get("body", "")), cta=str(value.get("cta", "")), disclosure=str(value.get("disclosure", "")), claims=tuple(GeneratedClaim(str(x.get("text", "")), tuple(x.get("source_evidence_ids") or ()), x.get("claim_kind")) for x in value.get("claims", [])))
def _failure(exc):
    text = type(exc).__name__.lower()
    category = ProviderFailureCategory.TIMEOUT if "timeout" in text else ProviderFailureCategory.RATE_LIMIT if "rate" in text else ProviderFailureCategory.AUTHENTICATION if "auth" in text else ProviderFailureCategory.UNKNOWN_PROVIDER_ERROR
    return ProviderFailure(category, "OpenAI content generation failed")
