"""
AI API Endpoints
"""

from fastapi import APIRouter, Depends

from app.ai.config import ai_settings
from app.schemas.ai import AIChatRequest, AIChatResponse
from app.services.ai_service import AIService

router = APIRouter(
    prefix="/ai",
    tags=["AI"],
)


def get_ai_service() -> AIService:
    """
    Return a fresh AIService instance.
    """
    return AIService()


@router.post(
    "/chat",
    response_model=AIChatResponse,
)
def chat(
    request: AIChatRequest,
    service: AIService = Depends(get_ai_service),
):
    """
    Send a prompt to the configured AI provider.
    """
    return service.chat(request)


@router.get("/debug")
def debug_ai():
    """
    Temporary debugging endpoint.
    Remove this endpoint after AI integration is complete.
    """
    key = (ai_settings.openai_api_key or "").strip()

    return {
        "provider": ai_settings.default_provider,
        "model": ai_settings.openai_default_model,
        "key_head": key[:20],
        "key_tail": key[-6:] if len(key) >= 6 else key,
        "key_length": len(key),
    }