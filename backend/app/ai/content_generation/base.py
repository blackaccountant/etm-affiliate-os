from abc import ABC, abstractmethod
from app.content_intelligence.generation_contracts import ContentGenerationPrompt, GenerationParameters, ProviderGenerationResult

class ContentGenerationProvider(ABC):
    @abstractmethod
    def generate(self, prompt: ContentGenerationPrompt, output_schema: dict, parameters: GenerationParameters, model: str) -> ProviderGenerationResult: ...
