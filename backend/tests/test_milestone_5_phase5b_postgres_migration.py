"""Opt-in local PostgreSQL migration gate for durable distribution intent."""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings


if not os.getenv("ETM_G5_DATABASE_URL"):
    pytest.skip("Requires the explicitly guarded ETM_G5_DATABASE_URL PostgreSQL test database.", allow_module_level=True)


g5_url = make_url(os.getenv("ETM_G5_DATABASE_URL") or "")
if g5_url.host != "127.0.0.1" or g5_url.port != 5432 or g5_url.database != "etm_affiliate_os_g5_test":
    raise RuntimeError("Phase 5B PostgreSQL gate requires only the guarded local G5 test database.")


@pytest.fixture
def g5_engine():
    database_url = g5_url.render_as_string(hide_password=False)
    original = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = database_url
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        yield config, engine
    finally:
        if "config" in locals():
            command.upgrade(config, "head")
        if "engine" in locals():
            engine.dispose()
        settings.DATABASE_URL = original


def test_distribution_runs_migration_upgrade_and_downgrade(g5_engine):
    config, engine = g5_engine
    try:
        inspector = inspect(engine)
        assert "distribution_runs" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("distribution_runs")}
        assert {
            "id", "generated_content_artifact_id", "content_evaluation_id", "platform", "account_reference",
            "destination", "status", "idempotency_key", "prepared_content_body", "payload_fingerprint", "scheduled_for",
            "external_post_id", "external_url", "result_metadata", "failure_category", "error_summary",
            "publishing_started_at", "created_at", "updated_at", "completed_at",
        }.issubset(columns)
        assert any(set(item["column_names"]) == {"idempotency_key"} for item in inspector.get_unique_constraints("distribution_runs"))
        indexes = {item["name"] for item in inspector.get_indexes("distribution_runs")}
        assert {
            "ix_distribution_runs_generated_content_artifact_id",
            "ix_distribution_runs_content_evaluation_id",
            "ix_distribution_runs_status",
            "ix_distribution_runs_scheduled_for",
        }.issubset(indexes)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f8a9b0c1d2e3"
        command.downgrade(config, "f6a7b8c9d0e1")
        after = inspect(engine)
        assert "distribution_runs" not in after.get_table_names()
        assert "content_repurposing_runs" in after.get_table_names()
    finally:
        command.upgrade(config, "head")
