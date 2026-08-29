from app.ai.content_generation.openai import OpenAIContentGenerationProvider
from app.ai.content_generation.ollama import OllamaContentGenerationProvider

class ContentGenerationProviderFactory:
    _providers = {"openai": OpenAIContentGenerationProvider, "ollama": OllamaContentGenerationProvider}
    @classmethod
    def create(cls, provider: str):
        key = (provider or "").lower()
        if key not in cls._providers: raise ValueError(f"Unsupported content generation provider: {key}")
        return cls._providers[key]()
    @classmethod
    def available_providers(cls): return sorted(cls._providers)
