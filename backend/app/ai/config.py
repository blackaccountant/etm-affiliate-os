"""
AI Configuration

Central configuration for all AI providers.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class AISettings(BaseSettings):
    """
    AI configuration settings.
    """

    default_provider: str = Field(
        default="openai",
        alias="AI_PROVIDER",
    )

    openai_api_key: str = Field(
        default="",
        alias="OPENAI_API_KEY",
    )

    openai_default_model: str = Field(
        default="gpt-5.5",
        alias="OPENAI_DEFAULT_MODEL",
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_BASE_URL",
    )

    ollama_default_model: str = Field(
        default="llama3.1",
        alias="OLLAMA_DEFAULT_MODEL",
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


ai_settings = AISettings()