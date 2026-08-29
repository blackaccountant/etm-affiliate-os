import os
import uuid
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings

if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip("Requires a local disposable PostgreSQL database; set ETM_RUN_POSTGRES_INTEGRATION=1 to run.", allow_module_level=True)

raw_url = os.getenv("ETM_POSTGRES_INTEGRATION_URL")
if not raw_url: raise RuntimeError("ETM_POSTGRES_INTEGRATION_URL must be set for the PostgreSQL migration gate.")
base_url = make_url(raw_url)
if base_url.host != "127.0.0.1" or base_url.port != 5432: raise RuntimeError("Phase 4D PostgreSQL gate requires 127.0.0.1:5432.")

@contextmanager
def disposable_database():
    name=f"etm_phase4d_{uuid.uuid4().hex}"; admin=create_engine(str(base_url.set(database="postgres")),isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn: conn.execute(text(f'CREATE DATABASE "{name}"'))
        url=str(base_url.set(database=name))
        target_url=make_url(url)
        assert target_url.host == "127.0.0.1" and target_url.port == 5432 and target_url.database == name
        cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",url)
        previous_database_url = settings.DATABASE_URL
        try:
            # alembic/env.py intentionally obtains its URL from settings.
            # Bind that setting to this test's exact disposable database.
            settings.DATABASE_URL = url
            command.upgrade(cfg,"head")
        finally:
            settings.DATABASE_URL = previous_database_url
        engine=create_engine(url); yield name,engine
    finally:
        if "engine" in locals(): engine.dispose()
        with admin.connect() as conn:
            conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid <> pg_backend_pid()"),{"name":name})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()

def test_phase4d_artifact_migration_and_cleanup():
    with disposable_database() as (name,engine):
        assert name.startswith("etm_phase4d_")
        assert engine.url.host == "127.0.0.1" and engine.url.port == 5432
        with engine.connect() as conn:
            assert conn.execute(text("SELECT current_database()")).scalar_one() == name
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "d4e5f6a7b8c9"
        inspector = inspect(engine)
        assert "generated_content_artifacts" in inspector.get_table_names()
        columns={item["name"] for item in inspector.get_columns("generated_content_artifacts")}
        assert {"id","generation_run_id","content_brief_id","content_type","title","hook","body","call_to_action","affiliate_disclosure","claims","status","created_at","updated_at"}.issubset(columns)
        foreign_keys = {(item["constrained_columns"][0], item["referred_table"]) for item in inspector.get_foreign_keys("generated_content_artifacts")}
        assert {("generation_run_id", "content_generation_runs"), ("content_brief_id", "content_briefs")}.issubset(foreign_keys)
        assert any(set(item["column_names"]) == {"generation_run_id"} for item in inspector.get_unique_constraints("generated_content_artifacts"))
        index_names = {item["name"] for item in inspector.get_indexes("generated_content_artifacts")}
        assert {"ix_generated_content_artifacts_content_brief_id", "ix_generated_content_artifacts_status", "ix_generated_content_artifacts_brief_status"}.issubset(index_names)
    admin=create_engine(str(base_url.set(database="postgres")),isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn: assert name not in conn.execute(text("SELECT datname FROM pg_database WHERE datname=:name"),{"name":name}).scalars().all()
    finally: admin.dispose()
