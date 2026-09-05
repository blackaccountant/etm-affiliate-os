import asyncio
import inspect

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import app.main as main_module
from app.core.api_security import Authority, operation_authority, resolve_authority
from app.database import session
from app.main import app, lifespan


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _scope(method: str, path: str) -> dict:
    return {"type": "http", "method": method, "path": path, "headers": []}


def test_health_remains_exact_and_dependency_free(monkeypatch):
    def fail_if_called():
        raise AssertionError("health must not invoke the readiness probe")

    monkeypatch.setattr(main_module, "database_is_ready", fail_if_called)

    response = _client().get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"success": True, "status": "healthy"}


def test_ready_success_is_public_and_not_cached(monkeypatch):
    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)

    response = _client().get("/ready")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"success": True, "status": "ready"}
    assert resolve_authority(app, _scope("GET", "/ready")) is Authority.PUBLIC
    assert operation_authority("GET", "/ready") is Authority.PUBLIC
    assert app.openapi()["paths"]["/ready"]["get"]["security"] == []
    assert _client().get("/products/").status_code == 401


def test_ready_expected_database_failure_is_generic_and_not_cached(monkeypatch):
    monkeypatch.setattr(main_module, "database_is_ready", lambda: False)

    response = _client().get("/ready")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"success": False, "status": "not_ready"}


def test_ready_unexpected_probe_failure_does_not_leak_details(monkeypatch):
    detail = "postgresql+psycopg2://db-user@db.internal:5432/etm"

    def fail_probe():
        raise RuntimeError(detail)

    monkeypatch.setattr(main_module, "database_is_ready", fail_probe)

    response = _client().get("/ready")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"success": False, "status": "not_ready"}
    assert detail not in response.text
    assert "db.internal" not in response.text
    assert "psycopg2" not in response.text


def test_database_probe_uses_only_read_only_context_managed_select_one(monkeypatch):
    calls = []

    class Connection:
        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            calls.append("exit")

        def execute(self, statement):
            calls.append(("execute", str(statement)))

        def commit(self):
            raise AssertionError("readiness probe must not commit")

    class Engine:
        def connect(self):
            calls.append("connect")
            return Connection()

    monkeypatch.setattr(session, "engine", Engine())

    assert session.database_is_ready() is True
    assert calls == ["connect", "enter", ("execute", "SELECT 1"), "exit"]
    source = inspect.getsource(session.database_is_ready).lower()
    assert "sessionlocal" not in source
    assert "create_all" not in source
    assert "alembic" not in source
    assert ".commit(" not in source


def test_database_probe_translates_expected_sqlalchemy_connectivity_failure(monkeypatch):
    class FailingEngine:
        def connect(self):
            raise OperationalError("SELECT 1", {}, RuntimeError("connection refused"))

    monkeypatch.setattr(session, "engine", FailingEngine())

    assert session.database_is_ready() is False


def test_startup_does_not_depend_on_readiness_probe(monkeypatch):
    from app.system import routes

    starts = []

    def fail_if_called():
        raise AssertionError("startup must not invoke the readiness probe")

    monkeypatch.setattr(main_module, "database_is_ready", fail_if_called)
    monkeypatch.setattr(routes.runtime, "start_retry_manager", lambda: starts.append(True) or True)
    monkeypatch.setattr(routes.runtime, "close", lambda: None)

    async def enter_lifespan():
        async with lifespan(app):
            assert starts == [True]

    asyncio.run(enter_lifespan())


def test_retry_manager_state_does_not_gate_ready_database(monkeypatch):
    from app.system import routes

    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)
    monkeypatch.setattr(routes.runtime, "retry_manager_running", lambda: False)

    response = _client().get("/ready")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"success": True, "status": "ready"}
