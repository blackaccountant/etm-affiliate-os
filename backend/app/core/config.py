import re
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


HTTP_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


# Resolve the backend directory from this file:
# backend/app/core/config.py
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Explicitly load backend/.env regardless of the current working directory.
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    APP_NAME: str
    ENV: str

    DATABASE_URL: str

    # These opaque credentials are deliberately supplied only through settings.
    # Empty or unsafe credentials leave protected API operations fail-closed.
    OPERATOR_API_TOKEN: str = ""
    SERVICE_API_TOKEN: str = ""
    OPERATOR_SESSION_TTL_SECONDS: int = 3600
    OPERATOR_SESSION_COOKIE_NAME: str = "etm_operator_session"
    OPERATOR_SESSION_COOKIE_SECURE: bool = True

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

    def api_security_configuration_error(self) -> str | None:
        """Return a safe configuration error without exposing credential values."""
        operator_token = self.OPERATOR_API_TOKEN
        service_token = self.SERVICE_API_TOKEN

        if not operator_token or not service_token:
            return "API bearer credentials are not configured"
        if len(operator_token) < 32 or len(service_token) < 32:
            return "API bearer credentials do not meet the minimum length"
        if operator_token == service_token:
            return "API bearer credentials must be distinct"
        return None

    def operator_session_configuration_error(self) -> str | None:
        """Return a safe browser-session configuration error."""
        if not 300 <= self.OPERATOR_SESSION_TTL_SECONDS <= 28800:
            return "operator session TTL is outside the permitted range"
        name = self.OPERATOR_SESSION_COOKIE_NAME
        if not HTTP_TOKEN_RE.fullmatch(name):
            return "operator session cookie name is invalid"
        if self.ENV.lower() in {"production", "prod"} and not self.OPERATOR_SESSION_COOKIE_SECURE:
            return "production operator sessions require secure cookies"
        return None


settings = Settings()
