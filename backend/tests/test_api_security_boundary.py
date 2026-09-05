import secrets

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.api_security import (
    Authority,
    _identity_from_header,
    authority_inventory,
    is_authorized,
    operation_authority,
    registered_operations,
    resolve_authority,
)
from app.core.config import settings
from app.main import app


# Generated at test runtime: no credential values are stored in the repository.
OPERATOR_TOKEN = secrets.token_urlsafe(48)
SERVICE_TOKEN = secrets.token_urlsafe(48)


def _client(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_API_TOKEN", OPERATOR_TOKEN)
    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", SERVICE_TOKEN)
    return TestClient(app, raise_server_exceptions=False)


def _scope(method, path):
    return {"type": "http", "method": method, "path": path, "headers": []}


def test_exact_authority_inventory_and_public_boundary():
    inventory = authority_inventory(app)
    assert sum(inventory.values()) == 69
    assert inventory == {
        Authority.PUBLIC: 3,
        Authority.OPERATOR: 11,
        Authority.SERVICE: 8,
        Authority.DUAL: 47,
    }
    public = {
        (method, path)
        for method, path in registered_operations(app)
        if operation_authority(method, path) is Authority.PUBLIC
    }
    assert public == {
        ("GET", "/"),
        ("GET", "/health"),
        ("GET", "/affiliate-links/go/{tracking_code}"),
    }
    assert all(method not in {"POST", "PUT", "PATCH", "DELETE"} for method, _ in public)


def test_parameterized_public_boundary_and_unknown_paths_are_not_public():
    assert resolve_authority(app, _scope("GET", "/")) is Authority.PUBLIC
    assert resolve_authority(app, _scope("GET", "/health")) is Authority.PUBLIC
    assert resolve_authority(app, _scope("GET", "/affiliate-links/go/abc")) is Authority.PUBLIC
    assert resolve_authority(app, _scope("GET", "/affiliate-links/abc")) is Authority.DUAL
    assert resolve_authority(app, _scope("GET", "/not-a-registered-path")) is None


def test_missing_malformed_and_invalid_credentials_return_401_without_secrets(monkeypatch):
    client = _client(monkeypatch)
    for headers in ({}, {"Authorization": "Basic anything"}, {"Authorization": "Bearer invalid"}):
        response = client.get("/products/", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert OPERATOR_TOKEN not in response.text
        assert SERVICE_TOKEN not in response.text


def test_identity_authority_matrix_and_configuration_fail_closed(monkeypatch):
    client = _client(monkeypatch)
    operator = _identity_from_header(f"Bearer {OPERATOR_TOKEN}", settings)
    service = _identity_from_header(f"Bearer {SERVICE_TOKEN}", settings)
    assert operator is Authority.OPERATOR
    assert service is Authority.SERVICE
    assert is_authorized(operator, Authority.OPERATOR)
    assert not is_authorized(operator, Authority.SERVICE)
    assert is_authorized(operator, Authority.DUAL)
    assert is_authorized(service, Authority.SERVICE)
    assert not is_authorized(service, Authority.OPERATOR)
    assert is_authorized(service, Authority.DUAL)
    assert client.post("/system/run", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"}).status_code == 403
    assert client.post("/products/", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 403
    assert client.post("/products/", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"}).status_code == 422
    assert client.post("/workers/product-hunter", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 422
    assert client.post("/ai/chat", headers={"Authorization": f"Bearer {OPERATOR_TOKEN}"}).status_code == 422
    assert client.post("/ai/chat", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}).status_code == 422

    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", OPERATOR_TOKEN)
    assert _identity_from_header(f"Bearer {OPERATOR_TOKEN}", settings) is None
    monkeypatch.setattr(settings, "SERVICE_API_TOKEN", "short")
    assert _identity_from_header(f"Bearer {OPERATOR_TOKEN}", settings) is None
    monkeypatch.setattr(settings, "OPERATOR_API_TOKEN", "")
    assert _identity_from_header(f"Bearer {SERVICE_TOKEN}", settings) is None


def test_public_runtime_and_cors_preflight_are_not_blocked(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/health").status_code == 200
    response = client.options(
        "/products/",
        headers={"Origin": "http://localhost:5500", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200


def test_openapi_matches_runtime_authority_policy():
    schema = app.openapi()
    assert schema["components"]["securitySchemes"] == {
        "BearerAuth": {"type": "http", "scheme": "bearer"}
    }
    public_count = protected_count = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            operation = schema["paths"][route.path][method.lower()]
            if operation_authority(method, route.path) is Authority.PUBLIC:
                public_count += 1
                assert operation["security"] == []
            else:
                protected_count += 1
                assert operation["security"] == [{"BearerAuth": []}]
    assert (public_count, protected_count) == (3, 66)
