"""
AI Schemas
"""

from pydantic import BaseModel, Field


class AIChatRequest(BaseModel):
    """
    AI chat request.
    """

    prompt: str = Field(
        ...,
        min_length=1,
        description="Prompt to send to the AI.",
    )

    provider: str | None = Field(
        default=None,
        description="Optional provider override.",
    )

    model: str | None = Field(
        default=None,
        description="Optional model override.",
    )


class AIChatResponse(BaseModel):
    """
    AI chat response.
    """

    provider: str

    model: str

    content: str

    success: bool

    execution_time: float

    error: str | None = None