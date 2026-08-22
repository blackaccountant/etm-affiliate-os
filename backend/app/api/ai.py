"""
AI API Endpoints
"""

from fastapi import APIRouter, Depends

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
    Send a prompt to the production AI provider.
    """
    return service.chat(request)
