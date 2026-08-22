"""
AI Configuration

Central configuration for the production AI provider.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve backend directory:
# backend/app/ai/config.py -> backend
BACKEND_DIR = Path(__file__).resolve().parents[2]

ENV_FILE = BACKEND_DIR / ".env"


class AISettings(BaseSettings):
    """
    Production AI configuration.

    ETM Affiliate OS uses OpenAI as its AI provider.
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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


ai_settings = AISettings()
