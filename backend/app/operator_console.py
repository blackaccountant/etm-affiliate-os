"""Mounted operator-console infrastructure kept outside the business API inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.core.api_security import Authority, _identity_from_header
from app.core.config import settings
from app.core.operator_session import operator_session_registry


FRONTEND_DIRECTORY = Path(__file__).resolve().parents[2] / "frontend" / "dashboard"


def _no_store(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    return response


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(settings.OPERATOR_SESSION_COOKIE_NAME, path="/")


def _session_payload(record: Any, csrf_token: str) -> dict[str, str | bool]:
    return {
        "authenticated": True,
        "authority": record.authority,
        "expires_at": record.expires_at.isoformat(),
        "csrf_token": csrf_token,
    }


async def login(request: Request) -> Response:
    if settings.operator_session_configuration_error() is not None:
        return _no_store(JSONResponse({"detail": "Not authenticated"}, status_code=401))
    identity = _identity_from_header(request.headers.get("authorization"), settings)
    if identity is None:
        return _no_store(JSONResponse({"detail": "Not authenticated"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}))
    if identity is not Authority.OPERATOR:
        return _no_store(JSONResponse({"detail": "Forbidden"}, status_code=403))

    operator_session_registry.revoke(request.cookies.get(settings.OPERATOR_SESSION_COOKIE_NAME))
    session_token, csrf_token, record = operator_session_registry.create(settings.OPERATOR_SESSION_TTL_SECONDS)
    response = _no_store(JSONResponse(_session_payload(record, csrf_token)))
    response.set_cookie(
        key=settings.OPERATOR_SESSION_COOKIE_NAME,
        value=session_token,
        max_age=settings.OPERATOR_SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.OPERATOR_SESSION_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )
    return response


async def session_status(request: Request) -> Response:
    if settings.operator_session_configuration_error() is not None:
        return _no_store(JSONResponse({"detail": "Not authenticated"}, status_code=401))
    session_token = request.cookies.get(settings.OPERATOR_SESSION_COOKIE_NAME)
    record = operator_session_registry.validate(session_token)
    if record is None:
        response = _no_store(JSONResponse({"detail": "Not authenticated"}, status_code=401))
        if session_token:
            _clear_cookie(response)
        return response
    # The browser obtains this value after login/reload; it is not the session ID.
    return _no_store(JSONResponse(_session_payload(record, record.csrf_token)))


async def logout(request: Request) -> Response:
    session_token = request.cookies.get(settings.OPERATOR_SESSION_COOKIE_NAME)
    record = operator_session_registry.validate(session_token)
    if record is None:
        return _no_store(JSONResponse({"detail": "Not authenticated"}, status_code=401))
    if not operator_session_registry.validate_csrf(session_token, request.headers.get("x-csrf-token")):
        return _no_store(JSONResponse({"detail": "Forbidden"}, status_code=403))
    operator_session_registry.revoke(session_token)
    response = _no_store(JSONResponse({"authenticated": False}))
    _clear_cookie(response)
    return response


operator_console = Starlette(
    routes=[
        Route("/session/login", login, methods=["POST"]),
        Route("/session", session_status, methods=["GET"]),
        Route("/session/logout", logout, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(FRONTEND_DIRECTORY), html=True)),
    ]
)
