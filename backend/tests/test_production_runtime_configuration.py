import asyncio
import secrets

import pytest

from app.core.config import (
    DEVELOPMENT_CORS_ALLOWED_ORIGINS,
    PRODUCTION_REQUIRES_SINGLE_PROCESS,
    Settings,
)


def _token() -> str:
    return secrets.token_urlsafe(48)


def _settings(**overrides) -> Settings:
    values = {
        "APP_NAME": "ETM test runtime",
        "ENV": "development",
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "OPERATOR_API_TOKEN": _token(),
        "SERVICE_API_TOKEN": _token(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("environment", ["production", "prod", " PRODUCTION ", "PrOd"])
def test_production_environment_aliases(environment):
    assert _settings(ENV=environment).is_production is True
    assert _settings(ENV="development").is_production is False


def test_development_cors_defaults_preserve_legacy_local_origins():
    assert _settings().cors_allowed_origins == list(DEVELOPMENT_CORS_ALLOWED_ORIGINS)


def test_production_cors_defaults_to_no_cross_origin_access():
    assert _settings(ENV="production").cors_allowed_origins == []


def test_explicit_cors_origins_are_trimmed_and_deduplicated_stably():
    runtime_settings = _settings(
        CORS_ALLOWED_ORIGINS=" https://operator.example.test ,http://localhost:3000, https://operator.example.test "
    )

    assert runtime_settings.cors_allowed_origins == [
        "https://operator.example.test",
        "http://localhost:3000",
    ]


@pytest.mark.parametrize(
    "origins",
    [
        "*",
        "https://operator.example.test/path",
        "https://operator.example.test?query=value",
        "https://operator.example.test#fragment",
        "operator.example.test",
        "ftp://operator.example.test",
        "https://:443",
        "https://operator example.test",
        "https://*",
        "https://operator.example.test:invalid",
    ],
)
def test_invalid_cors_origins_are_rejected(origins):
    with pytest.raises(ValueError, match="CORS allowed origins"):
        _settings(CORS_ALLOWED_ORIGINS=origins).cors_allowed_origins


def test_production_runtime_validation_accepts_safe_configuration():
    assert _settings(ENV="production").production_runtime_configuration_error() is None


def test_production_runtime_validation_rejects_unsafe_configuration():
    assert "SQL echo" in _settings(ENV="production", DATABASE_ECHO=True).production_runtime_configuration_error()
    assert "minimum length" in _settings(ENV="production", OPERATOR_API_TOKEN="short").production_runtime_configuration_error()
    assert "secure cookies" in _settings(
        ENV="production", OPERATOR_SESSION_COOKIE_SECURE=False
    ).production_runtime_configuration_error()
    assert "CORS" in _settings(
        ENV="production", CORS_ALLOWED_ORIGINS="https://operator.example.test/path"
    ).production_runtime_configuration_error()


def test_database_engine_uses_runtime_echo_liveness_and_recycle_settings(monkeypatch):
    from app.database import session

    captured = {}
    sentinel_engine = object()

    def fake_create_engine(database_url, **kwargs):
        captured["database_url"] = database_url
        captured.update(kwargs)
        return sentinel_engine

    monkeypatch.setattr(session, "create_engine", fake_create_engine)
    runtime_settings = _settings(DATABASE_ECHO=True, DATABASE_POOL_RECYCLE_SECONDS=1234)

    assert session.create_database_engine(runtime_settings) is sentinel_engine
    assert captured == {
        "database_url": "sqlite+pysqlite:///:memory:",
        "echo": True,
        "pool_pre_ping": True,
        "pool_recycle": 1234,
    }


def test_lifespan_fails_before_starting_runtime_for_invalid_production_settings(monkeypatch):
    from app.main import app, lifespan

    monkeypatch.setattr(
        Settings,
        "production_runtime_configuration_error",
        lambda _: "production CORS configuration is invalid",
    )

    async def enter_lifespan():
        async with lifespan(app):
            raise AssertionError("invalid production configuration must not start the runtime")

    with pytest.raises(RuntimeError, match="invalid production runtime configuration"):
        asyncio.run(enter_lifespan())


def test_single_process_contract_is_explicit_until_shared_runtime_state_exists():
    assert PRODUCTION_REQUIRES_SINGLE_PROCESS is True
