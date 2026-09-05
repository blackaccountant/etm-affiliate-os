"""Centralized API bearer authentication and route authority policy."""

from __future__ import annotations

import hmac
from collections import Counter
from enum import StrEnum
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from app.core.config import Settings, settings
from app.core.operator_session import operator_session_registry


class Authority(StrEnum):
    PUBLIC = "PUBLIC"
    OPERATOR = "OPERATOR"
    SERVICE = "SERVICE"
    DUAL = "DUAL"


# The PR1C1 authority manifest.  All registered operations omitted from this
# table are deliberately DUAL (never public).
_PUBLIC_OPERATIONS = frozenset({
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/affiliate-links/go/{tracking_code}"),
})
_OPERATOR_OPERATIONS = frozenset({
    ("POST", "/affiliate-earnings/{earning_id}/pay"),
    ("POST", "/affiliate-payouts/create"),
    ("POST", "/affiliate-payouts/{payout_id}/complete"),
    ("POST", "/affiliate-payouts/{payout_id}/fail"),
    ("POST", "/affiliate-payouts/{payout_id}/process"),
    ("POST", "/affiliate-payouts/{payout_id}/retry"),
    ("POST", "/optimization/approvals/decide"),
    ("POST", "/products/"),
    ("DELETE", "/products/{product_id}"),
    ("PUT", "/products/{product_id}"),
    ("POST", "/publisher/publish/{queue_id}"),
})
_SERVICE_OPERATIONS = frozenset({
    ("POST", "/content/generation-runs/{content_generation_run_id}/launch"),
    ("POST", "/content/repurposing-runs/{content_repurposing_run_id}/launch"),
    ("POST", "/discovery/runs/{run_id}/execute"),
    ("POST", "/discovery/runs/{run_id}/launch"),
    ("POST", "/system/command/run-affiliate"),
    ("POST", "/system/command/run-product-discovery"),
    ("POST", "/system/run"),
    ("POST", "/workers/product-hunter"),
})


def operation_authority(method: str, path_template: str) -> Authority:
    """Classify a registered operation; the safe default is DUAL, not PUBLIC."""
    operation = (method.upper(), path_template)
    if operation in _PUBLIC_OPERATIONS:
        return Authority.PUBLIC
    if operation in _OPERATOR_OPERATIONS:
        return Authority.OPERATOR
    if operation in _SERVICE_OPERATIONS:
        return Authority.SERVICE
    return Authority.DUAL


def registered_operations(app: FastAPI) -> list[tuple[str, str]]:
    return [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or set()
    ]


def authority_inventory(app: FastAPI) -> Counter[Authority]:
    return Counter(
        operation_authority(method, path)
        for method, path in registered_operations(app)
    )


def resolve_authority(app: FastAPI, scope: dict[str, Any]) -> Authority | None:
    """Resolve a concrete request path through FastAPI's parameterized routes."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return operation_authority(scope["method"], route.path)
    return None


def _identity_from_header(authorization: str | None, configured: Settings) -> Authority | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
        return None
    if configured.api_security_configuration_error() is not None:
        return None
    if hmac.compare_digest(token, configured.OPERATOR_API_TOKEN):
        return Authority.OPERATOR
    if hmac.compare_digest(token, configured.SERVICE_API_TOKEN):
        return Authority.SERVICE
    return None


def is_authorized(identity: Authority, required: Authority) -> bool:
    """Return whether an authenticated identity may invoke an operation."""
    return required is Authority.DUAL or identity is required


def _authentication_failure() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Not authenticated"},
        headers={"WWW-Authenticate": "Bearer"},
    )


class ApiSecurityMiddleware(BaseHTTPMiddleware):
    """Authenticate and authorize all registered API operations before handlers."""

    def __init__(self, app: Any, *, configured: Settings = settings) -> None:
        super().__init__(app)
        self.configured = configured

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # CORS preflight must reach CORSMiddleware even for protected endpoints.
        if request.method == "OPTIONS":
            return await call_next(request)

        application = request.scope.get("app")
        authority = resolve_authority(application, request.scope) if application else None
        # Docs, OpenAPI, and unknown paths are not API-public operations.  They
        # retain their ordinary infrastructure/404 handling.
        if authority is None or authority is Authority.PUBLIC:
            return await call_next(request)

        authorization = request.headers.get("authorization")
        session_token = None
        session_authenticated = False
        if authorization is not None:
            identity = _identity_from_header(authorization, self.configured)
        else:
            session_token = request.cookies.get(self.configured.OPERATOR_SESSION_COOKIE_NAME)
            session = None
            if self.configured.operator_session_configuration_error() is None:
                session = operator_session_registry.validate(session_token)
            identity = Authority.OPERATOR if session is not None else None
            session_authenticated = session is not None
        if identity is None:
            return _authentication_failure()
        if not is_authorized(identity, authority):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        if session_authenticated and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not operator_session_registry.validate_csrf(session_token, request.headers.get("x-csrf-token")):
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


def install_api_security(app: FastAPI) -> None:
    """Install runtime enforcement and an OpenAPI schema that mirrors it."""
    app.add_middleware(ApiSecurityMiddleware)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        components["BearerAuth"] = {"type": "http", "scheme": "bearer"}
        for path, operations in schema.get("paths", {}).items():
            for method, operation in operations.items():
                if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    continue
                authority = operation_authority(method.upper(), path)
                operation["security"] = [] if authority is Authority.PUBLIC else [{"BearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
