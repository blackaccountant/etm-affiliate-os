"""
AI Service
"""

from app.ai.manager import AIManager
from app.schemas.ai import AIChatRequest, AIChatResponse


class AIService:
    """
    Service layer for AI operations.
    """

    def chat(self, request: AIChatRequest) -> AIChatResponse:
        manager = AIManager(provider=request.provider)

        result = manager.generate(
            prompt=request.prompt,
            model=request.model,
        )

        return AIChatResponse(
            provider=result.provider,
            model=result.model,
            content=result.content,
            success=result.success,
            execution_time=result.execution_time,
            error=result.error,
        )