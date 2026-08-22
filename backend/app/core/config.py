from pathlib import Path

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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()