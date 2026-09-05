"""Application logging context and bounded request-completion logging."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from typing import Awaitable, Callable
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response


BACKGROUND_REQUEST_ID = "-"
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_request_id: ContextVar[str] = ContextVar("logging_request_id", default=BACKGROUND_REQUEST_ID)


def get_logger(name: str) -> logging.Logger:
    """Return an application logger that inherits the configured root handler."""
    return logging.getLogger(name)


def generate_request_id() -> str:
    """Create the only request ID accepted by the production logging contract."""
    return uuid4().hex


def request_id() -> str:
    """Return the current trusted request ID, or the background sentinel."""
    return _request_id.get()


def bind_request_id(value: str) -> Token[str]:
    """Bind a trusted server-generated request ID for one request scope."""
    if not REQUEST_ID_RE.fullmatch(value):
        raise ValueError("request ID must be 32 lowercase hexadecimal characters")
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    """Restore the prior request scope, including after an exception path."""
    _request_id.reset(token)


def _route_marker(request: Request) -> str:
    """Use a resolved application route template, never the inbound raw path."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/") and len(template) <= 256:
        return template
    return "-"


async def request_completion_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    logger: logging.Logger,
) -> Response:
    """Attach a generated ID and emit one safe record for each completed request."""
    token = bind_request_id(generate_request_id())
    response: Response | None = None
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id()
        return response
    finally:
        try:
            status = response.status_code if response is not None else "unhandled"
            logger.info(
                "request_completed method=%s route=%s status=%s",
                request.method,
                _route_marker(request),
                status,
            )
        except Exception:
            pass
        reset_request_id(token)
