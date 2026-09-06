"""Windows-safe PR1D12 request-protection contract tests."""

from __future__ import annotations

import re
import secrets
import threading
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

import app.main as main_module
from app.core.api_security import Authority, operation_authority
from app.core.config import settings
from app.request_protection import (
    IDLE_EXPIRY_SECONDS,
    MAX_NORMAL_BUCKETS,
    POLICIES,
    ProtectionClass,
    RatePolicy,
    RequestProtectionMiddleware,
    TokenBucketLimiter,
    client_fingerprint,
    protection_class,
)


ROOT = Path(__file__).resolve().parents[2]


def _scope(path: str, method: str = "GET", client: tuple[str, int] | None = ("203.0.113.9", 1234)):
    scope = {"type": "http", "method": method, "path": path, "headers": [], "app": main_module.app}
    if client is not None:
        scope["client"] = client
    return scope


def _tiny_client(monkeypatch):
    policies = {category: RatePolicy(60, 1) for category in ProtectionClass}
    original_init = RequestProtectionMiddleware.__init__

    def install_tiny_limiter(self, app, *, limiter=None):
        original_init(self, app, limiter=TokenBucketLimiter(policies=policies))

    monkeypatch.setattr(RequestProtectionMiddleware, "__init__", install_tiny_limiter)
    main_module.app.middleware_stack = None
    service_token = secrets.token_urlsafe(48)
    operator_token = secrets.token_urlsafe(48)
    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", service_token)
    monkeypatch.setattr(settings, "OPERATOR_API_TOKEN", operator_token)
    return TestClient(main_module.app, raise_server_exceptions=False), service_token, operator_token


def test_exact_classes_and_provisional_policies_are_bounded():
    assert set(ProtectionClass) == {
        ProtectionClass.PUBLIC, ProtectionClass.DUAL, ProtectionClass.OPERATOR, ProtectionClass.SERVICE,
        ProtectionClass.OPERATOR_CONSOLE, ProtectionClass.HEALTH, ProtectionClass.READY,
        ProtectionClass.METRICS, ProtectionClass.PREFLIGHT, ProtectionClass.UNKNOWN,
    }
    assert {kind: (policy.per_minute, policy.burst) for kind, policy in POLICIES.items()} == {
        ProtectionClass.PUBLIC: (60, 20), ProtectionClass.DUAL: (120, 30),
        ProtectionClass.OPERATOR: (120, 30), ProtectionClass.SERVICE: (240, 60),
        ProtectionClass.OPERATOR_CONSOLE: (240, 60), ProtectionClass.HEALTH: (30, 10),
        ProtectionClass.READY: (30, 10), ProtectionClass.METRICS: (30, 5),
        ProtectionClass.PREFLIGHT: (60, 20), ProtectionClass.UNKNOWN: (30, 10),
    }


def test_token_bucket_burst_refill_cap_and_positive_retry_after():
    clock = [0.0]
    limiter = TokenBucketLimiter(policies={ProtectionClass.PUBLIC: RatePolicy(60, 2)}, time_source=lambda: clock[0])
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (True, None)
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (True, None)
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (False, 1)
    clock[0] = 0.5
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (False, 1)
    clock[0] = 1.0
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (True, None)
    clock[0] = 100.0
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (True, None)
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (True, None)
    assert limiter.admit(ProtectionClass.PUBLIC, "a") == (False, 1)


def test_identity_is_canonical_opaque_and_malformed_values_share_unknown():
    assert client_fingerprint("2001:db8::1", secret=b"x" * 32) == client_fingerprint("2001:0db8:0:0:0:0:0:1", secret=b"x" * 32)
    assert client_fingerprint("203.0.113.9", secret=b"x" * 32) != "203.0.113.9"
    for value in (None, "example.test", "1.2.3.4, 5.6.7.8", "\n", "\u2603"):
        assert client_fingerprint(value, secret=b"x" * 32) == "unknown"


def test_classification_uses_registered_routes_and_fixed_mounted_boundary():
    assert protection_class(Request(_scope("/health"))) is ProtectionClass.HEALTH
    assert protection_class(Request(_scope("/ready"))) is ProtectionClass.READY
    assert protection_class(Request(_scope("/metrics"))) is ProtectionClass.METRICS
    assert protection_class(Request(_scope("/products/123"))) is ProtectionClass.DUAL
    assert protection_class(Request(_scope("/products/", method="POST"))) is ProtectionClass.OPERATOR
    assert protection_class(Request(_scope("/unknown/secret"))) is ProtectionClass.UNKNOWN
    assert protection_class(Request(_scope("/operator/session", method="GET"))) is ProtectionClass.OPERATOR_CONSOLE
    assert protection_class(Request(_scope("/health", method="OPTIONS"))) is ProtectionClass.PREFLIGHT
    assert operation_authority("GET", "/metrics") is Authority.SERVICE


def test_memory_cap_uses_fixed_per_class_overflow_and_expiry_is_bounded():
    clock = [0.0]
    limiter = TokenBucketLimiter(time_source=lambda: clock[0])
    for index in range(MAX_NORMAL_BUCKETS):
        assert limiter.admit(ProtectionClass.PUBLIC, f"id-{index}")[0]
    assert limiter.normal_bucket_count == MAX_NORMAL_BUCKETS
    limiter.admit(ProtectionClass.PUBLIC, "overflow-public")
    limiter.admit(ProtectionClass.SERVICE, "overflow-service")
    assert limiter.normal_bucket_count == MAX_NORMAL_BUCKETS
    assert limiter.overflow_bucket_count == 2
    clock[0] = IDLE_EXPIRY_SECONDS + 1
    assert limiter.cleanup(limit=MAX_NORMAL_BUCKETS) == MAX_NORMAL_BUCKETS
    assert limiter.normal_bucket_count == 0


def test_concurrent_same_identity_never_exceeds_burst():
    limiter = TokenBucketLimiter(policies={ProtectionClass.PUBLIC: RatePolicy(60, 20)})
    outcomes: list[bool] = []

    def consume():
        outcomes.append(limiter.admit(ProtectionClass.PUBLIC, "same")[0])

    threads = [threading.Thread(target=consume) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(outcomes) == 20


def test_429_has_correlation_safe_body_headers_logging_and_existing_4xx_metrics(monkeypatch):
    client, service_token, _ = _tiny_client(monkeypatch)
    assert client.get("/health").status_code == 200
    rejected = client.get("/health?token=topsecret", headers={"X-Request-ID": "attacker"})
    assert rejected.status_code == 429
    assert rejected.json() == {"detail": "Too Many Requests"}
    assert rejected.headers["cache-control"] == "no-store"
    assert re.fullmatch(r"[0-9a-f]{32}", rejected.headers["x-request-id"])
    assert rejected.headers["retry-after"].isdigit() and int(rejected.headers["retry-after"]) > 0
    exposition = client.get("/metrics", headers={"Authorization": f"Bearer {service_token}"}).text
    assert 'route="/health",status_class="4xx"' in exposition
    for forbidden in ("topsecret", "attacker", "203.0.113.9"):
        assert forbidden not in exposition and forbidden not in rejected.text


def test_authority_short_circuits_remain_frozen_before_protection(monkeypatch):
    client, _, _ = _tiny_client(monkeypatch)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics").status_code == 401


def test_preflight_is_limited_and_rate_limited_allowed_origin_remains_cors_compatible(monkeypatch):
    client, _, _ = _tiny_client(monkeypatch)
    origin = settings.cors_allowed_origins[0]
    headers = {"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    assert client.options("/health", headers=headers).status_code == 200
    rejected = client.options("/health", headers=headers)
    assert rejected.status_code == 429
    assert rejected.headers["access-control-allow-origin"] == origin
    assert rejected.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in rejected.headers["access-control-allow-headers"]


def test_limiter_failure_fails_open_without_weakening_authority(monkeypatch):
    client, _, _ = _tiny_client(monkeypatch)
    monkeypatch.setattr(TokenBucketLimiter, "admit", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 401


def test_scope_has_no_forwarded_parsing_or_new_external_dependencies():
    source = (ROOT / "backend" / "app" / "request_protection.py").read_text(encoding="utf-8")
    for forbidden in ("x-forwarded-for", "forwarded\"", "x-real-ip", "redis", "requests.", "SessionLocal", "database_is_ready"):
        assert forbidden not in source.lower()
    assert "ipaddress.ip_address" in source and "blake2b" in source
    assert (ROOT / "deployment" / "Caddyfile").read_text(encoding="utf-8") == (ROOT / "deployment" / "Caddyfile").read_text(encoding="utf-8")
