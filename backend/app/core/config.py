from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the backend directory from this file:
# backend/app/core/config.py
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Explicitly load backend/.env regardless of the current working directory.
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    APP_NAME: str
    ENV: str

    DATABASE_URL: str

    OPENAI_API_KEY: str = ""
    OPENAI_DEFAULT_MODEL: str = "gpt-5.5"

    DEFAULT_AI_PROVIDER: str = "openai"
    CONTENT_AI_PROVIDER: str = "openai"
    OPENAI_CONTENT_MODEL: str = "gpt-5.5"
    OPENAI_CONTENT_TIMEOUT_SECONDS: float = 30.0
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_CONTENT_MODEL: str = ""
    OLLAMA_CONTENT_TIMEOUT_SECONDS: float = 30.0
    EXECUTION_LEASE_SECONDS: int = 90
    EXECUTION_HEARTBEAT_SECONDS: int = 30
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = ""
    RESEND_FROM_NAME: str = ""
    RESEND_REQUEST_TIMEOUT_SECONDS: float = Field(default=10.0, ge=0.1, le=30.0)

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
