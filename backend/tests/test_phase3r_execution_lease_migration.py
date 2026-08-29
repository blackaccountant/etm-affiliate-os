"""Guarded PostgreSQL roundtrip proof for the Phase 3R F9 lease migration."""

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app.core.config import settings


F9 = "f9a0b1c2d3e4"
F8 = "f8a9b0c1d2e3"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Phase 3R F9 proof requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database and "g5" in _url.database.lower() and "test" in _url.database.lower()):
    raise RuntimeError("Phase 3R F9 proof requires the guarded local G5 test database.")


def _config():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _url.render_as_string(hide_password=False))
    return config


def _current(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _columns(engine):
    return {column["name"]: column for column in inspect(engine).get_columns("executions")}


@contextmanager
def _guarded_alembic(config):
    """Alembic env.py resolves the URL from settings, not Config alone."""
    old = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = _url.render_as_string(hide_password=False)
        yield
    finally:
        settings.DATABASE_URL = old


def test_f9_execution_lease_roundtrip_preserves_existing_execution_data():
    config = _config()
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    with _guarded_alembic(config):
        command.upgrade(config, "head")
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    mission_id = str(uuid4())
    worker_name = f"F9 Worker {uuid4()}"
    try:
        assert _current(engine) == expected_head
        assert expected_head == F9
        before = _columns(engine)
        assert {"lease_owner", "lease_generation", "lease_expires_at"} <= set(before)
        assert before["lease_owner"]["nullable"] is True
        assert before["lease_generation"]["nullable"] is False
        assert before["lease_expires_at"]["nullable"] is True
        assert {"id", "mission_id", "workflow_name", "status", "input_data", "retry_count", "max_retries"} <= set(before)

        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO missions (id, name, objective, workflow_name, status, input_data, created_at, updated_at)
                VALUES (:id, :name, :objective, :workflow, :status, :payload, :now, :now)
            """), {"id": mission_id, "name": "F9 roundtrip", "objective": "preserve data", "workflow": "f9_test", "status": "RUNNING", "payload": "{\"example\":true}", "now": now})
            connection.execute(text("""
                INSERT INTO workers (name, worker_type, capabilities, status, current_mission_id, missions_completed, missions_failed, success_rate, created_at, updated_at)
                VALUES (:name, :worker_type, CAST(:capabilities AS json), :status, :mission_id, 0, 0, 100.0, :now, :now)
            """), {"name": worker_name, "worker_type": "Test", "capabilities": "[]", "status": "BUSY", "mission_id": mission_id, "now": now})
            connection.execute(text("""
                INSERT INTO executions (mission_id, mission_name, worker_name, workflow_name, status, result_data, input_data, started_at, duration, retry_count, max_retries, failure_type, error, lease_owner, lease_generation)
                VALUES (:mission_id, :mission_name, :worker_name, :workflow_name, :status, :result_data, :input_data, :now, :duration, :retry_count, :max_retries, :failure_type, :error, :lease_owner, :lease_generation)
            """), {"mission_id": mission_id, "mission_name": "F9 roundtrip", "worker_name": worker_name, "workflow_name": "f9_test", "status": "RUNNING", "result_data": "{\"preserved\":true}", "input_data": "{\"input\":true}", "now": now, "duration": 1.25, "retry_count": 1, "max_retries": 3, "failure_type": "NETWORK", "error": "safe error", "lease_owner": "f9-owner", "lease_generation": 7})

        with _guarded_alembic(config):
            command.downgrade(config, F8)
        engine.dispose()
        assert _current(engine) == F8
        after_down = _columns(engine)
        assert not {"lease_owner", "lease_generation", "lease_expires_at"} & set(after_down)
        assert {"id", "mission_id", "workflow_name", "status", "input_data", "retry_count", "max_retries"} <= set(after_down)
        assert {"missions", "workers", "executions", "distribution_runs"} <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT workflow_name, status, result_data, input_data, retry_count, max_retries, failure_type, error
                FROM executions WHERE mission_id = :id
            """), {"id": mission_id}).mappings().one()
        assert dict(row) == {"workflow_name": "f9_test", "status": "RUNNING", "result_data": "{\"preserved\":true}", "input_data": "{\"input\":true}", "retry_count": 1, "max_retries": 3, "failure_type": "NETWORK", "error": "safe error"}

        with _guarded_alembic(config):
            command.upgrade(config, "head")
        engine.dispose()
        assert _current(engine) == expected_head
        after_up = _columns(engine)
        assert {"lease_owner", "lease_generation", "lease_expires_at"} <= set(after_up)
        assert {"missions", "workers", "executions", "distribution_runs"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
