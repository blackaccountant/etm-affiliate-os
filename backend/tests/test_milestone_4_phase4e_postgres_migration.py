import os, uuid
from contextlib import contextmanager
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app.core.config import settings
if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1": pytest.skip("Requires a local disposable PostgreSQL database; set ETM_RUN_POSTGRES_INTEGRATION=1 to run.",allow_module_level=True)
base_url=make_url(os.getenv("ETM_POSTGRES_INTEGRATION_URL") or "")
if base_url.host!="127.0.0.1" or base_url.port!=5432: raise RuntimeError("Phase 4E PostgreSQL gate requires 127.0.0.1:5432.")
@contextmanager
def database():
    name=f"etm_phase4e_{uuid.uuid4().hex}"; admin=create_engine(str(base_url.set(database="postgres")),isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c: c.execute(text(f'CREATE DATABASE "{name}"'))
        url=str(base_url.set(database=name)); previous=settings.DATABASE_URL
        try:
            settings.DATABASE_URL=url; cfg=Config("alembic.ini"); cfg.set_main_option("sqlalchemy.url",url); command.upgrade(cfg,"head")
        finally: settings.DATABASE_URL=previous
        engine=create_engine(url); yield name,engine
    finally:
        if "engine" in locals(): engine.dispose()
        with admin.connect() as c:
            c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:n AND pid<>pg_backend_pid()"),{"n":name}); c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()
def test_content_evaluations_migration_and_cleanup():
    with database() as (name,engine):
        assert name.startswith("etm_phase4e_") and engine.url.host=="127.0.0.1" and engine.url.port==5432
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar_one()==name; assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()=="e5f6a7b8c9d0"
        inspector=inspect(engine); assert "content_evaluations" in inspector.get_table_names()
        columns={x["name"] for x in inspector.get_columns("content_evaluations")}; assert {"id","artifact_id","content_brief_id","generation_run_id","factual_grounding_score","offer_alignment_score","intent_alignment_score","clarity_score","cta_score","compliance_score","overall_score","decision","approved","evaluator_version","policy_version","claim_results","compliance_flags","unsupported_claims","missing_evidence_ids","revision_reasons","rejection_reasons","created_at","updated_at"}.issubset(columns)
        assert any(set(x["column_names"])=={"artifact_id","evaluator_version","policy_version"} for x in inspector.get_unique_constraints("content_evaluations"))
