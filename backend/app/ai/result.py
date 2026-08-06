"""
AI Result Model

Defines the standard response returned by every AI provider
used within ETM Affiliate OS.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AIResult(BaseModel):
    """
    Standard AI response object.

    Every provider (OpenAI, Ollama, etc.) should return this
    model so the rest of the application never depends on
    provider-specific response formats.
    """

    success: bool = True

    provider: str

    model: str

    content: str

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    execution_time: float = 0.0

    metadata: Dict[str, Any] = Field(default_factory=dict)

    error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)