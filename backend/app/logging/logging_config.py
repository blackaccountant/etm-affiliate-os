"""Bounded standard-library production logging configuration."""

from __future__ import annotations

import logging
import re
import sys
import traceback
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from app.logging.logger import BACKGROUND_REQUEST_ID, request_id


REDACTION_TOKEN = "[REDACTED]"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | request_id=%(request_id)s | %(message)s"
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|token|secret|api[_.-]?key|provider[_.-]?key|password|passwd|session|cookie|csrf|"
    r"database[_.-]?url|recipient|(?:^|[_-])to(?:$|[_-])|email|body|message|content)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE)
_HEADER_VALUE = re.compile(
    r"\b(authorization|token|cookie|set-cookie|session(?:[-_ ]?token)?|"
    r"csrf(?:[-_ ]?token)?|database[-_ ]?url|"
    r"(?:operator|service|provider)(?:[-_ ]?api)?[-_ ]?(?:token|key|secret)|api[-_ ]?key|password|passwd)"
    r"\s*[:=]\s*([^,;\s]+)",
    re.IGNORECASE,
)
_SECRET_QUERY = {"token", "access_token", "id_token", "api_key", "apikey", "key", "secret", "password", "passwd"}


def _is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY.search(key))


def _redact_urls(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return raw
        if not parsed.scheme or not parsed.netloc:
            return raw
        hostname = parsed.hostname or ""
        try:
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            return REDACTION_TOKEN
        netloc = hostname + port
        if parsed.username is not None or parsed.password is not None:
            netloc = f"{REDACTION_TOKEN}@{netloc}"
        query = "&".join(
            f"{key}={REDACTION_TOKEN if key.lower() in _SECRET_QUERY else value}"
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        )
        return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))

    return re.sub(r"(?:postgres(?:ql)?(?:\+[A-Za-z0-9_]+)?|https?)://[^\s<>'\"]+", replace, text)


def redact_text(value: str) -> str:
    """Redact known secret-bearing text deterministically and idempotently."""
    text = _redact_urls(value)
    text = _BEARER.sub(f"Bearer {REDACTION_TOKEN}", text)
    text = _HEADER_VALUE.sub(lambda match: f"{match.group(1)}={REDACTION_TOKEN}", text)
    return _EMAIL.sub(REDACTION_TOKEN, text)


def redact_value(value: Any, *, sensitive: bool = False) -> Any:
    """Copy and sanitize supported values without introspecting arbitrary objects."""
    if sensitive:
        return REDACTION_TOKEN
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {key: redact_value(item, sensitive=_is_sensitive_key(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    return f"<untrusted {type(value).__name__}>"


class SensitiveDataFilter(logging.Filter):
    """Attach request context and sanitize records before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id() or BACKGROUND_REQUEST_ID
        record.msg = redact_value(record.msg)
        if isinstance(record.args, Mapping):
            record.args = redact_value(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(redact_value(item) for item in record.args)
        elif record.args:
            record.args = redact_value(record.args)
        return True


class RedactingFormatter(logging.Formatter):
    """Apply final defense to rendered messages and traceback output."""

    def formatException(self, exc_info: Any) -> str:  # noqa: N802 - logging API name
        return redact_text("".join(traceback.format_exception(*exc_info)))

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging() -> None:
    """Configure one stdout application sink with central redaction."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
