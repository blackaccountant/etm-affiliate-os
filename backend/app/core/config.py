import re
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


HTTP_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

DEVELOPMENT_CORS_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)

# Operator sessions and retry management are process-local until shared
# infrastructure is introduced by a later deployment phase.
PRODUCTION_REQUIRES_SINGLE_PROCESS = True


def _is_valid_origin_hostname(hostname: str) -> bool:
    try:
        ip_address(hostname)
    except ValueError:
        return all(HOSTNAME_LABEL_RE.fullmatch(label) for label in hostname.split("."))
    return True


# Resolve the backend directory from this file:
# backend/app/core/config.py
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Explicitly load backend/.env regardless of the current working directory.
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    APP_NAME: str
    ENV: str

    DATABASE_URL: str
    DATABASE_ECHO: bool = False
    DATABASE_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60, le=86400)
    CORS_ALLOWED_ORIGINS: str = ""

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

    @property
    def is_production(self) -> bool:
        """Whether this settings instance represents a production environment."""
        return self.ENV.strip().lower() in {"production", "prod"}

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Return validated cross-origin browser authorities for this runtime."""
        configured_origins = self.CORS_ALLOWED_ORIGINS.strip()
        if not configured_origins:
            return [] if self.is_production else list(DEVELOPMENT_CORS_ALLOWED_ORIGINS)

        normalized_origins: list[str] = []
        seen_origins: set[str] = set()
        for configured_origin in configured_origins.split(","):
            origin = configured_origin.strip()
            if not origin:
                continue
            if origin == "*":
                raise ValueError("CORS allowed origins must not contain a wildcard")

            try:
                parsed = urlsplit(origin)
                port = parsed.port
            except ValueError as exc:
                raise ValueError("CORS allowed origins contain an invalid origin") from exc

            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or not _is_valid_origin_hostname(parsed.hostname)
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.netloc.endswith(":")
            ):
                raise ValueError("CORS allowed origins contain an invalid origin")

            hostname = parsed.hostname.lower()
            normalized_hostname = f"[{hostname}]" if ":" in hostname else hostname
            normalized_origin = f"{parsed.scheme.lower()}://{normalized_hostname}"
            if port is not None:
                normalized_origin += f":{port}"

            if normalized_origin not in seen_origins:
                normalized_origins.append(normalized_origin)
                seen_origins.add(normalized_origin)
        return normalized_origins

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
        if self.is_production and not self.OPERATOR_SESSION_COOKIE_SECURE:
            return "production operator sessions require secure cookies"
        return None

    def production_runtime_configuration_error(self) -> str | None:
        """Return a safe production startup error without exposing settings values."""
        if not self.is_production:
            return None

        if error := self.api_security_configuration_error():
            return error
        if error := self.operator_session_configuration_error():
            return error
        if self.DATABASE_ECHO:
            return "production database SQL echo must be disabled"
        try:
            self.cors_allowed_origins
        except ValueError:
            return "production CORS configuration is invalid"
        return None


settings = Settings()
