"""Bounded, process-local inbound request protection for the one-worker runtime."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match, Mount

from app.core.api_security import Authority, operation_authority
from app.core.config import settings


class ProtectionClass(StrEnum):
    PUBLIC = "PUBLIC"
    DUAL = "DUAL"
    OPERATOR = "OPERATOR"
    SERVICE = "SERVICE"
    OPERATOR_CONSOLE = "OPERATOR_CONSOLE"
    HEALTH = "HEALTH"
    READY = "READY"
    METRICS = "METRICS"
    PREFLIGHT = "PREFLIGHT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RatePolicy:
    per_minute: int
    burst: int


POLICIES: dict[ProtectionClass, RatePolicy] = {
    ProtectionClass.PUBLIC: RatePolicy(60, 20),
    ProtectionClass.DUAL: RatePolicy(120, 30),
    ProtectionClass.OPERATOR: RatePolicy(120, 30),
    ProtectionClass.SERVICE: RatePolicy(240, 60),
    ProtectionClass.OPERATOR_CONSOLE: RatePolicy(240, 60),
    ProtectionClass.HEALTH: RatePolicy(30, 10),
    ProtectionClass.READY: RatePolicy(30, 10),
    ProtectionClass.METRICS: RatePolicy(30, 5),
    ProtectionClass.PREFLIGHT: RatePolicy(60, 20),
    ProtectionClass.UNKNOWN: RatePolicy(30, 10),
}

MAX_NORMAL_BUCKETS = 4096
IDLE_EXPIRY_SECONDS = 600.0
MAX_CLEANUP_PER_REQUEST = 32
_PROCESS_SECRET = secrets.token_bytes(32)


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


def client_fingerprint(host: object, *, secret: bytes = _PROCESS_SECRET) -> str:
    """Return an opaque per-process identity; malformed values share ``unknown``."""
    if not isinstance(host, str):
        return "unknown"
    try:
        canonical = str(ipaddress.ip_address(host))
    except ValueError:
        return "unknown"
    return hashlib.blake2b(canonical.encode("ascii"), key=secret, digest_size=16).hexdigest()


def _bind_api_route(request: Request) -> APIRoute | None:
    """Resolve and retain a registered template without reading a raw route value."""
    application = request.scope.get("app")
    if application is None:
        return None
    for route in application.routes:
        if not isinstance(route, APIRoute):
            continue
        match, _ = route.matches(request.scope)
        if match in {Match.FULL, Match.PARTIAL}:
            request.scope["route"] = route
            return route
    return None


def protection_class(request: Request) -> ProtectionClass:
    """Classify through registered routes and the frozen API authority vocabulary."""
    route = _bind_api_route(request)
    if request.method == "OPTIONS":
        return ProtectionClass.PREFLIGHT
    if route is not None:
        if route.path == "/health":
            return ProtectionClass.HEALTH
        if route.path == "/ready":
            return ProtectionClass.READY
        if route.path == "/metrics":
            return ProtectionClass.METRICS
        return ProtectionClass(operation_authority(request.method, route.path))

    application = request.scope.get("app")
    if application is not None:
        for mounted in application.routes:
            if isinstance(mounted, Mount) and mounted.path == "/operator":
                match, _ = mounted.matches(request.scope)
                if match in {Match.FULL, Match.PARTIAL}:
                    return ProtectionClass.OPERATOR_CONSOLE
    return ProtectionClass.UNKNOWN


class TokenBucketLimiter:
    """Lock-protected token buckets with bounded normal and per-class overflow state."""

    def __init__(
        self,
        *,
        policies: dict[ProtectionClass, RatePolicy] = POLICIES,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policies = policies
        self._time_source = time_source
        self._normal: OrderedDict[tuple[ProtectionClass, str], _Bucket] = OrderedDict()
        self._overflow: dict[ProtectionClass, _Bucket] = {}
        self._lock = threading.RLock()

    @property
    def normal_bucket_count(self) -> int:
        with self._lock:
            return len(self._normal)

    @property
    def overflow_bucket_count(self) -> int:
        with self._lock:
            return len(self._overflow)

    def cleanup(self, *, now: float | None = None, limit: int = MAX_CLEANUP_PER_REQUEST) -> int:
        """Discard only a bounded number of oldest idle normal buckets."""
        current = self._time_source() if now is None else now
        removed = 0
        with self._lock:
            while self._normal and removed < limit:
                _, bucket = next(iter(self._normal.items()))
                if current - bucket.updated_at < IDLE_EXPIRY_SECONDS:
                    break
                self._normal.popitem(last=False)
                removed += 1
        return removed

    def _bucket(self, category: ProtectionClass, identity: str, now: float) -> _Bucket:
        key = (category, identity)
        bucket = self._normal.get(key)
        if bucket is not None:
            self._normal.move_to_end(key)
            return bucket
        if len(self._normal) >= MAX_NORMAL_BUCKETS:
            return self._overflow.setdefault(category, _Bucket(float(self._policies[category].burst), now))
        bucket = _Bucket(float(self._policies[category].burst), now)
        self._normal[key] = bucket
        return bucket

    def admit(self, category: ProtectionClass, identity: str, *, now: float | None = None) -> tuple[bool, int | None]:
        """Consume one token or return a positive, whole-second retry delay."""
        current = self._time_source() if now is None else now
        self.cleanup(now=current)
        with self._lock:
            policy = self._policies[category]
            bucket = self._bucket(category, identity, current)
            elapsed = max(0.0, current - bucket.updated_at)
            rate = policy.per_minute / 60.0
            bucket.tokens = min(float(policy.burst), bucket.tokens + elapsed * rate)
            bucket.updated_at = current
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, None
            wait = (1.0 - bucket.tokens) / rate
            return False, max(1, math.ceil(wait))


def rate_limited_response(retry_after: int, request: Request) -> JSONResponse:
    """Return the fixed, non-disclosing rejection response."""
    headers = {"Retry-After": str(max(1, retry_after)), "Cache-Control": "no-store"}
    origin = request.headers.get("origin")
    if request.method == "OPTIONS" and origin in settings.cors_allowed_origins:
        headers.update({
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
            "Vary": "Origin",
        })
        requested_headers = request.headers.get("access-control-request-headers")
        if requested_headers:
            headers["Access-Control-Allow-Headers"] = requested_headers
    return JSONResponse(status_code=429, content={"detail": "Too Many Requests"}, headers=headers)


class RequestProtectionMiddleware(BaseHTTPMiddleware):
    """Apply every request to one bounded policy, failing open only on limiter faults."""

    def __init__(self, app: Any, *, limiter: TokenBucketLimiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter or TokenBucketLimiter()

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        category = ProtectionClass.UNKNOWN
        try:
            category = protection_class(request)
            admitted, retry_after = self.limiter.admit(category, client_fingerprint(getattr(request.client, "host", None)))
            if not admitted:
                return rate_limited_response(retry_after or 1, request)
        except Exception:
            # Do not let bounded bookkeeping create an availability outage.
            logging.getLogger(__name__).warning("request_protection_internal_failure class=%s", category)
        return await call_next(request)
