"""PR1D10 static and unit contracts; no DB, network or host operations."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from app.logging.logger import (
    BACKGROUND_REQUEST_ID,
    REQUEST_ID_HEADER,
    bind_request_id,
    generate_request_id,
    request_completion_middleware,
    request_id,
)
from app.logging.logging_config import (
    LOG_FORMAT,
    REDACTION_TOKEN,
    RedactingFormatter,
    SensitiveDataFilter,
    redact_text,
    redact_value,
)


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "deployment" / "start-production.sh"
RUNBOOK = ROOT / "docs" / "LOGGING.md"
MAIN = ROOT / "backend" / "app" / "main.py"
CONFIG = ROOT / "backend" / "app" / "logging" / "logging_config.py"


def _logger_stream():
    stream = io.StringIO()
    logger = logging.getLogger("pr1d10.contract")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    logger.addHandler(handler)
    return logger, stream


def _client():
    app = FastAPI()
    logger, stream = _logger_stream()

    @app.middleware("http")
    async def logging_middleware(request, call_next):
        return await request_completion_middleware(request, call_next, logger)

    @app.get("/items/{item_id}")
    async def item(item_id: str):
        return {"item": item_id}

    @app.get("/handled")
    async def handled():
        raise HTTPException(status_code=418, detail="handled")

    return TestClient(app, raise_server_exceptions=False), stream


def test_formatter_uses_stdlib_stdout_contract_and_stable_fields():
    source = CONFIG.read_text(encoding="utf-8")
    assert "import logging" in source and "StreamHandler(sys.stdout)" in source
    assert "FileHandler" not in source and "basicConfig" in source
    assert "logging.INFO" in source
    assert "logging.getLogger(\"sqlalchemy.engine\").setLevel(logging.WARNING)" in source
    for field in ("%(asctime)s", "%(levelname)s", "%(name)s", "%(request_id)s", "%(message)s"):
        assert field in LOG_FORMAT
    assert request_id() == BACKGROUND_REQUEST_ID


def test_generated_request_ids_are_server_shaped_and_bound_only_when_valid():
    generated = {generate_request_id() for _ in range(8)}
    assert len(generated) == 8
    assert all(re.fullmatch(r"[0-9a-f]{32}", value) for value in generated)
    with pytest.raises(ValueError):
        bind_request_id("bad\nrequest-id")


def test_request_ids_ignore_inbound_values_reset_and_emit_one_bounded_completion_record():
    client, stream = _client()
    malicious = "attacker\nAuthorization: Bearer topsecret"
    first = client.get("/items/customer-secret?token=query-secret", headers={"X-Request-ID": malicious, "X-Correlation-ID": "a" * 5000, "Authorization": "Bearer header-secret", "Cookie": "session=cookie-secret"})
    second = client.get("/handled", headers={"X-Request-ID": "0" * 32})
    assert first.status_code == 200 and second.status_code == 418
    first_id, second_id = first.headers[REQUEST_ID_HEADER], second.headers[REQUEST_ID_HEADER]
    assert re.fullmatch(r"[0-9a-f]{32}", first_id)
    assert re.fullmatch(r"[0-9a-f]{32}", second_id)
    assert first_id != second_id and first_id != "0" * 32
    assert request_id() == BACKGROUND_REQUEST_ID
    output = stream.getvalue()
    assert output.count("request_completed") == 2
    assert "method=GET" in output and "status=200" in output and "status=418" in output
    assert "route=/items/{item_id}" in output
    for secret in ("customer-secret", "query-secret", "topsecret", "header-secret", "cookie-secret", malicious):
        assert secret not in output


def test_context_resets_after_unhandled_error_and_isolated_tasks_do_not_share_ids():
    logger, stream = _logger_stream()
    scope = {"type": "http", "method": "GET", "path": "/unmatched-secret", "headers": []}

    async def fail(_request):
        assert re.fullmatch(r"[0-9a-f]{32}", request_id())
        raise RuntimeError("unhandled")

    async def observe(index):
        request = Request({**scope, "path": f"/items/{index}"})

        async def respond(_request):
            await asyncio.sleep(0)
            return Response()

        response = await request_completion_middleware(request, respond, logger)
        return response.headers[REQUEST_ID_HEADER]

    with pytest.raises(RuntimeError, match="unhandled"):
        asyncio.run(request_completion_middleware(Request(scope), fail, logger))
    async def collect_ids():
        return await asyncio.gather(*(observe(index) for index in range(8)))

    ids = asyncio.run(collect_ids())
    assert len(set(ids)) == 8
    assert request_id() == BACKGROUND_REQUEST_ID
    assert "unmatched-secret" not in stream.getvalue()


def test_unmatched_route_uses_a_sentinel_instead_of_the_raw_path():
    client, stream = _client()
    response = client.get("/missing/SECRET123?token=query-secret")
    assert response.status_code == 404
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers[REQUEST_ID_HEADER])
    output = stream.getvalue()
    assert "route=-" in output
    assert "SECRET123" not in output and "query-secret" not in output


@pytest.mark.parametrize("value", [
    "Authorization: Bearer topsecret", {"authorization": "Bearer topsecret"},
    {"PASSWORD": "supersecret"}, {"database": {"url": "postgresql://user:pass@db.internal/app"}},
    {"recipient": "person@example.test", "body": "private content"},
    ["safe", {"api_key": "provider-secret"}], ("x", {"csrf-token": "csrf-secret"}),
    {"cookie": "session-secret", "set-cookie": "session=other-secret"},
    {"session": "session-value", "provider_key": "provider-key", "to_email": "to@example.test"},
    {"outer": [{"Authorization": "Bearer mixed-case"}], "database_url": "postgres://user:db-pass@host/db"},
    {"items": {"safe", "set@example.test"}},
])
def test_supported_values_are_redacted_without_mutating_caller_containers(value):
    original = repr(value)
    rendered = repr(redact_value(value))
    for secret in ("topsecret", "supersecret", "user:pass", "person@example.test", "private content", "provider-secret", "csrf-secret", "session-secret", "other-secret", "session-value", "provider-key", "to@example.test", "mixed-case", "db-pass", "set@example.test"):
        assert secret not in rendered
    assert repr(value) == original
    assert redact_value(redact_value(value)) == redact_value(value)


@pytest.mark.parametrize("raw", [
    "postgresql://user:supersecret@db.internal/app",
    "https://user:password@example.com/path",
    "https://example.test/callback?token=abcdef123456&safe=yes",
    "https://example.test/?api_key=secret",
    "email recipient@example.test Authorization: Bearer abcdef OPERATOR_API_TOKEN=operator-secret DATABASE_URL=postgresql://user:db-secret@db.internal/app",
])
def test_text_redaction_covers_urls_query_secrets_bearer_and_email(raw):
    output = redact_text(raw)
    assert REDACTION_TOKEN in output
    for secret in ("supersecret", "user:password", "abcdef123456", "secret", "recipient@example.test", "abcdef", "operator-secret", "db-secret"):
        assert secret not in output
    assert redact_text(output) == output


def test_formatter_redacts_percent_arguments_preformatted_messages_exceptions_and_tracebacks():
    logger, stream = _logger_stream()
    logger.info("Authorization=%s", "Bearer argument-secret")
    logger.info("payload=%s", {"password": "payload-secret"})
    logger.info("url=%s", "postgresql://user:argument-db-secret@host/db")
    logger.info("nested=%s", {"outer": {"api_key": "nested-secret", "safe": "ok"}})
    logger.info("provider failure %s", {"token": "arg-secret"})
    logger.info("Authorization: Bearer preformatted-secret")
    logger.info("already %s", REDACTION_TOKEN)
    try:
        raise ValueError("token=exception-secret recipient@example.test")
    except ValueError:
        logger.exception("provider_failure")
    output = stream.getvalue()
    assert "ValueError" in output and REDACTION_TOKEN in output
    for secret in ("argument-secret", "payload-secret", "argument-db-secret", "nested-secret", "arg-secret", "preformatted-secret", "exception-secret", "recipient@example.test"):
        assert secret not in output


@pytest.mark.parametrize("url", [
    "postgresql://user:supersecret@db.internal/app",
    "postgres://user:secret@host/db",
    "https://user:password@example.com/path",
    "https://example.test/?token=secret",
    "https://example.test/?api_key=secret",
    "https://example.test/?access_token=secret",
    "https://example.test/?safe=value&token=secret&other=value",
])
def test_final_formatted_url_output_never_preserves_secret_values(url):
    logger, stream = _logger_stream()
    logger.info("url=%s", url)
    output = stream.getvalue()
    assert REDACTION_TOKEN in output
    for secret in ("supersecret", "user:secret", "user:password", "token=secret", "api_key=secret", "access_token=secret"):
        assert secret not in output


def test_unsupported_objects_are_not_introspected():
    class Dangerous:
        def __str__(self):
            raise AssertionError("must not stringify arbitrary values")

    assert redact_value(Dangerous()) == "<untrusted Dangerous>"


def test_launcher_and_main_preserve_frozen_topology_while_disabling_uvicorn_access_logs():
    launcher = LAUNCHER.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")
    assert launcher.count("--no-access-log") == 1
    for required in ("--host 127.0.0.1", '--port "$PORT"', "--workers 1", "--proxy-headers", "--forwarded-allow-ips 127.0.0.1"):
        assert required in launcher
    for forbidden in ("--reload", "0.0.0.0", "alembic", "create_all", "--log-level"):
        assert forbidden not in launcher.lower()
    assert "request_completion_middleware" in main
    assert "Failed to start retry manager: %s" not in main
    assert "Error during ETM Affiliate OS shutdown: %s" not in main


def test_runbook_documents_redaction_retention_scope_and_deferred_host_validation():
    document = RUNBOOK.read_text(encoding="utf-8")
    for phrase in ("journald", "application creates no log files", "deployment/host owner controls", "No external logging or monitoring platform", "Monitoring and alert policy belong to PR1D11", "Caddy access logging is not added", "[REDACTED]", "X-Request-ID", "Do not recover production secrets from Git"):
        assert phrase in document
    assert "Repository qualification does not prove Linux journald" in document
    assert "str(exc)" in document
    assert "monitoring SDK" not in document.lower()
