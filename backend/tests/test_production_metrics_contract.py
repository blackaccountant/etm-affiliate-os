"""PR1D11 Windows-safe metrics contract tests with no live service dependencies."""

from __future__ import annotations

import re
import secrets
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.api_security import Authority, operation_authority, resolve_authority
from app.core.config import settings
from app.monitoring import (
    ALLOWED_METHODS,
    ALLOWED_STATUS_CLASSES,
    METRICS_CONTENT_TYPE,
    MetricsRegistry,
    normalize_method,
    normalize_route,
    normalize_status_class,
)


ROOT = Path(__file__).resolve().parents[2]
CADDYFILE = ROOT / "deployment" / "Caddyfile"
LAUNCHER = ROOT / "deployment" / "start-production.sh"
DOCUMENT = ROOT / "docs" / "MONITORING.md"


def _client(monkeypatch):
    service_token = secrets.token_urlsafe(48)
    operator_token = secrets.token_urlsafe(48)
    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", service_token)
    monkeypatch.setattr(settings, "OPERATOR_API_TOKEN", operator_token)
    return TestClient(main_module.app, raise_server_exceptions=False), service_token, operator_token


def _metric_lines(text, name):
    return [line for line in text.splitlines() if line.startswith(name)]


def test_registry_has_only_the_exact_stable_metric_vocabulary():
    registry = MetricsRegistry()
    exposition = registry.render(retry_manager_running=True)
    names = {line.split()[0].split("{")[0] for line in exposition.splitlines() if line and not line.startswith("#")}
    assert names == {
        "etm_process_start_time_seconds",
        "etm_process_uptime_seconds",
        "etm_retry_manager_running",
    }
    registry.record_http_request("GET", "/items/{item_id}", 200, 0.25)
    names = {line.split()[0].split("{")[0] for line in registry.render(retry_manager_running=False).splitlines() if line and not line.startswith("#")}
    assert names == {
        "etm_process_start_time_seconds", "etm_process_uptime_seconds", "etm_retry_manager_running",
        "etm_http_requests_total", "etm_http_request_duration_seconds_count", "etm_http_request_duration_seconds_sum",
    }


def test_registry_uses_bounded_labels_and_cumulative_duration_pairs():
    registry = MetricsRegistry()
    registry.record_http_request("GET", "/items/{item_id}", 201, 0.25)
    registry.record_http_request("GET", "/items/{item_id}", 201, 0.5)
    registry.record_http_request("TRACE", "/raw/secret-value?token=bad", 799, -3)
    exposition = registry.render(retry_manager_running=True)
    assert 'method="GET",route="/items/{item_id}",status_class="2xx"' in exposition
    assert 'etm_http_requests_total{method="GET",route="/items/{item_id}",status_class="2xx"} 2' in exposition
    assert 'etm_http_request_duration_seconds_count{method="GET",route="/items/{item_id}",status_class="2xx"} 2' in exposition
    assert 'etm_http_request_duration_seconds_sum{method="GET",route="/items/{item_id}",status_class="2xx"} 0.750000000' in exposition
    assert 'method="OTHER",route="unmatched",status_class="other"' in exposition
    assert "secret-value" not in exposition and "token=bad" not in exposition


def test_registry_process_and_retry_gauges_are_safe():
    registry = MetricsRegistry()
    exposition = registry.render(retry_manager_running=True)
    assert registry.process_start_time_seconds > 0
    assert registry.process_uptime_seconds() >= 0
    assert "etm_retry_manager_running 1" in exposition
    assert "etm_retry_manager_running 0" in registry.render(retry_manager_running="yes")


def test_normalizers_have_fixed_domains():
    assert ALLOWED_METHODS == {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
    assert ALLOWED_STATUS_CLASSES == {"1xx", "2xx", "3xx", "4xx", "5xx", "other"}
    assert normalize_method("trace") == "OTHER"
    assert normalize_route("/products/{product_id}") == "/products/{product_id}"
    assert normalize_route("/products/raw-secret?token=value") == "unmatched"
    assert normalize_status_class(503) == "5xx"
    assert normalize_status_class("500") == "other"


def test_metrics_endpoint_is_service_only_and_does_not_probe_database(monkeypatch):
    client, service_token, operator_token = _client(monkeypatch)
    monkeypatch.setattr(main_module, "database_is_ready", lambda: (_ for _ in ()).throw(AssertionError("no DB probe")))
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": f"Bearer {operator_token}"}).status_code == 403
    response = client.get("/metrics", headers={"Authorization": f"Bearer {service_token}"})
    assert response.status_code == 200
    assert response.headers["content-type"] == METRICS_CONTENT_TYPE
    assert "etm_process_start_time_seconds" in response.text
    assert operation_authority("GET", "/metrics") is Authority.SERVICE
    assert resolve_authority(main_module.app, {"type": "http", "method": "GET", "path": "/metrics", "headers": []}) is Authority.SERVICE


def test_metrics_scrape_is_excluded_and_requests_are_template_safe(monkeypatch):
    client, service_token, _ = _client(monkeypatch)
    client.get("/health?email=person@example.test&token=secret")
    client.get("/missing/raw-value?request_id=bad")
    response = client.get("/metrics", headers={"Authorization": f"Bearer {service_token}"})
    assert 'route="/health",status_class="2xx"' in response.text
    assert 'route="unmatched",status_class="4xx"' in response.text
    for forbidden in ("person@example.test", "secret", "raw-value", "request_id", "token="):
        assert forbidden not in response.text
    before = len(_metric_lines(response.text, "etm_http_requests_total"))
    after = client.get("/metrics", headers={"Authorization": f"Bearer {service_token}"}).text
    assert len(_metric_lines(after, "etm_http_requests_total")) == before


def test_request_metrics_cover_post_4xx_5xx_and_preserve_request_correlation(monkeypatch):
    client, service_token, _ = _client(monkeypatch)
    response = client.post("/system/run", headers={"Authorization": f"Bearer {service_token}"})
    assert response.status_code == 422
    monkeypatch.setattr(main_module, "database_is_ready", lambda: False)
    response = client.get("/ready")
    assert response.status_code == 503
    health = client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", health.headers["x-request-id"])
    exposition = client.get("/metrics", headers={"Authorization": f"Bearer {service_token}"}).text
    assert 'method="POST",route="/system/run",status_class="4xx"' in exposition
    assert 'method="GET",route="/ready",status_class="5xx"' in exposition
    assert health.headers["x-request-id"] not in exposition


def test_metrics_bookkeeping_failure_cannot_break_a_successful_response(monkeypatch):
    client, _, _ = _client(monkeypatch)

    def fail_bookkeeping(*args, **kwargs):
        raise RuntimeError("do not expose this metric error")

    monkeypatch.setattr(main_module.metrics_registry, "record_http_request", fail_bookkeeping)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"success": True, "status": "healthy"}


def test_exposition_has_only_the_authorized_label_keys_and_no_database_runtime_dependency():
    registry = MetricsRegistry()
    registry.record_http_request("GET", "/health", 200, float("nan"))
    registry.record_http_request("POST", "/system/run", 422, float("inf"))
    exposition = registry.render(retry_manager_running=False)
    for line in _metric_lines(exposition, "etm_http_"):
        labels = re.search(r"\{([^}]*)\}", line)
        assert labels is not None
        assert [part.split("=", 1)[0] for part in labels.group(1).split(",")] == ["method", "route", "status_class"]
        assert "nan" not in line.lower() and "inf" not in line.lower()
    runtime_source = (ROOT / "backend" / "app" / "monitoring.py").read_text(encoding="utf-8")
    for forbidden in ("database_is_ready", "SessionLocal", "engine.connect", "requests.", "openai"):
        assert forbidden not in runtime_source


def test_frozen_health_ready_logging_and_edge_contracts_remain_present(monkeypatch):
    client, _, _ = _client(monkeypatch)
    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)
    assert client.get("/health").json() == {"success": True, "status": "healthy"}
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.headers["cache-control"] == "no-store"
    assert "--no-access-log" in LAUNCHER.read_text(encoding="utf-8")
    caddy = CADDYFILE.read_text(encoding="utf-8")
    assert 'respond "Not Found" 404' in caddy and "reverse_proxy 127.0.0.1:8000" in caddy


def test_monitoring_document_has_policy_and_deferred_ownership_contract():
    document = DOCUMENT.read_text(encoding="utf-8")
    for phrase in (
        "SERVICE authority only", "Caddy returns `404`", "DEPLOYMENT_DECISION_REQUIRED",
        "WARNING", "CRITICAL", "no database", "process-local", "request IDs",
        "external monitor", "live-host validation",
    ):
        assert phrase in document
    runtime_source = (ROOT / "backend" / "app" / "monitoring.py").read_text(encoding="utf-8").lower()
    assert not any(vendor in runtime_source for vendor in ("prometheus_client", "opentelemetry", "statsd", "datadog", "sentry"))
    assert re.search(r"alert delivery\s+daemon", document, flags=re.IGNORECASE)
    assert re.search(r"method.*route.*status_class", document, flags=re.DOTALL)
