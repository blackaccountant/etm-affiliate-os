from datetime import datetime, timedelta, timezone
import secrets

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.api_security import Authority, authority_inventory
from app.core.config import settings
from app.core.operator_session import OperatorSessionRegistry, operator_session_registry
from app.main import app


OPERATOR_TOKEN = secrets.token_urlsafe(48)
SERVICE_TOKEN = secrets.token_urlsafe(48)


@pytest.fixture(autouse=True)
def session_security_settings(monkeypatch):
    operator_session_registry.clear()
    monkeypatch.setattr(settings, "OPERATOR_API_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", SERVICE_TOKEN)
    monkeypatch.setattr(settings, "OPERATOR_SESSION_TTL_SECONDS", 3600)
    monkeypatch.setattr(settings, "OPERATOR_SESSION_COOKIE_NAME", "etm_operator_session")
    monkeypatch.setattr(settings, "OPERATOR_SESSION_COOKIE_SECURE", True)
    yield
    operator_session_registry.clear()


@pytest.mark.parametrize(
    "cookie_name",
    [
        "etm_operator_session",
        "ETM-Operator.Session",
        "session123",
        "session!#$%&'*+-.^_`|~",
    ],
)
def test_operator_session_cookie_name_accepts_http_token_grammar(monkeypatch, cookie_name):
    monkeypatch.setattr(settings, "OPERATOR_SESSION_COOKIE_NAME", cookie_name)

    assert settings.operator_session_configuration_error() is None


@pytest.mark.parametrize(
    "cookie_name",
    [
        "",
        " ",
        "bad name",
        "bad/name",
        "bad(name)",
        "bad@name",
        "bad:name",
        "bad[name]",
        "bad;name",
        "bad,name",
        "bad=name",
        "bad<name>",
        "bad{name}",
        "bad?name",
        "bad\\name",
        "bad\tname",
        "bad\nname",
        "bad\x00name",
        "sessión",
    ],
)
def test_operator_session_cookie_name_rejects_non_http_token_grammar(monkeypatch, cookie_name):
    monkeypatch.setattr(settings, "OPERATOR_SESSION_COOKIE_NAME", cookie_name)

    assert settings.operator_session_configuration_error() == "operator session cookie name is invalid"


def _client():
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)


def _login(client):
    response = client.post("/operator/session/login", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"})
    assert response.status_code == 200
    return response


def test_frozen_api_inventory_and_operator_mount_boundary():
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    assert len(routes) == 69
    assert authority_inventory(app) == {
        Authority.PUBLIC: 3,
        Authority.OPERATOR: 11,
        Authority.SERVICE: 8,
        Authority.DUAL: 47,
    }
    assert all(not route.path.startswith("/operator/") for route in routes)


def test_static_console_assets_are_public():
    client = _client()
    assert client.get("/operator/").status_code == 200
    assert client.get("/operator/app.js").status_code == 200
    assert client.get("/operator/styles.css").status_code == 200


def test_login_rejects_bad_credentials_without_leaking_secrets():
    client = _client()
    for headers in ({}, {"Authorization": "Basic no"}, {"Authorization": "Bearer invalid"}):
        response = client.post("/operator/session/login", headers=headers)
        assert response.status_code == 401
        assert OPERATOR_TOKEN not in response.text
        assert SERVICE_TOKEN not in response.text
    assert client.post("/operator/session/login", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 403


def test_login_sets_secure_operator_cookie_and_session_status_is_non_secret():
    client = _client()
    response = _login(client)
    body = response.json()
    cookie_value = client.cookies.get(settings.OPERATOR_SESSION_COOKIE_NAME)
    assert body["authenticated"] is True
    assert body["authority"] == "OPERATOR"
    assert body["csrf_token"]
    assert OPERATOR_TOKEN not in response.text
    assert cookie_value not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    status = client.get("/operator/session")
    assert status.status_code == 200
    assert status.json()["authority"] == "OPERATOR"
    assert status.json()["csrf_token"] == body["csrf_token"]
    assert status.headers["cache-control"] == "no-store"


def test_cookie_operator_authority_and_csrf_boundary():
    client = _client()
    csrf = _login(client).json()["csrf_token"]
    assert client.get("/system/status").status_code == 200
    assert client.post("/system/run").status_code == 403
    assert client.post("/optimization/recommendations/project").status_code == 403
    assert client.post("/optimization/recommendations/project", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/optimization/recommendations/project", headers={"X-CSRF-Token": csrf}).status_code == 422
    assert client.post("/products/", headers={"X-CSRF-Token": csrf}).status_code == 422


def test_bearer_precedence_and_existing_bearer_behavior():
    client = _client()
    _login(client)
    assert client.get("/system/status", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post("/optimization/recommendations/project", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"}).status_code == 422
    assert client.post("/workers/product-hunter", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 422


def test_logout_requires_csrf_and_revokes_session():
    client = _client()
    csrf = _login(client).json()["csrf_token"]
    assert client.post("/operator/session/logout").status_code == 403
    assert client.get("/operator/session").status_code == 200
    assert client.post("/operator/session/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/operator/session/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/operator/session").status_code == 401


def test_session_registry_expiry_and_invalid_configuration_fail_closed(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = [now]
    registry = OperatorSessionRegistry(clock=lambda: clock[0])
    token, csrf, _ = registry.create(300)
    assert registry.validate(token) is not None and registry.validate_csrf(token, csrf)
    clock[0] = now + timedelta(seconds=301)
    assert registry.validate(token) is None

    monkeypatch.setattr(settings, "OPERATOR_SESSION_TTL_SECONDS", 299)
    assert _client().post("/operator/session/login", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"}).status_code == 401


def test_cors_options_remains_unblocked():
    response = _client().options("/products/", headers={"Origin": "http://localhost:5500", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
