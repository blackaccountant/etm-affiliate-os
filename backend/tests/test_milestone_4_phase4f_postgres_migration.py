"""Opt-in local PostgreSQL schema gate for Phase 4F."""

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


base_url = make_url(os.getenv("ETM_POSTGRES_INTEGRATION_URL") or "")
if base_url.host != "127.0.0.1" or base_url.port != 5432:
    raise RuntimeError("Phase 4F PostgreSQL gate requires 127.0.0.1:5432.")


@contextmanager
def disposable_phase4f_database():
    name = f"etm_phase4f_{uuid.uuid4().hex}"
    admin = create_engine(str(base_url.set(database="postgres")), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = str(base_url.set(database=name))
        previous_url = settings.DATABASE_URL
        try:
            settings.DATABASE_URL = url
            config = Config("alembic.ini")
            config.set_main_option("sqlalchemy.url", url)
            command.upgrade(config, "head")
        finally:
            settings.DATABASE_URL = previous_url
        engine = create_engine(url)
        yield name, engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid <> pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def test_content_repurposing_runs_migration_and_cleanup():
    with disposable_phase4f_database() as (database_name, engine):
        assert database_name.startswith("etm_phase4f_")
        assert engine.url.host == "127.0.0.1" and engine.url.port == 5432
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one() == database_name
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f6a7b8c9d0e1"
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO discovery_runs (id, input_type, input_value, status, candidate_count, verified_count, selected_count, created_at, updated_at)
                VALUES ('run', 'URL', 'https://example.com', 'COMPLETED', 0, 0, 0, now(), now())
            """))
            connection.execute(text("""
                INSERT INTO discovery_candidates (id, run_id, source_adapter, source_type, canonical_domain, program_identity_key, dedupe_key, commission_model, verification_status, disposition, created_at, updated_at)
                VALUES ('candidate', 'run', 'official', 'official', 'example.com', 'program', 'dedupe', 'UNKNOWN', 'VERIFIED', 'SELECTED', now(), now())
            """))
            connection.execute(text("""
                INSERT INTO content_briefs (id, discovery_run_id, discovery_candidate_id, content_type, channel_intent, objective, call_to_action, required_disclosure, key_benefits, proof_points, target_keywords, constraints, idempotency_key, status, created_at, updated_at)
                VALUES ('brief', 'run', 'candidate', 'ARTICLE', 'SEO', 'facts', 'CHECK_DETAILS', 'AFFILIATE_DISCLOSURE_REQUIRED', '[]', '[]', '[]', '[]', 'brief', 'READY', now(), now())
            """))
            connection.execute(text("""
                INSERT INTO content_generation_runs (id, content_brief_id, idempotency_key, provider, model, prompt_version, generation_parameters, status, attempt_count, created_at, updated_at)
                VALUES ('generation', 'brief', 'generation', 'fake', 'fake', 'v1', '{}', 'COMPLETED', 1, now(), now())
            """))
            connection.execute(text("""
                INSERT INTO generated_content_artifacts (id, generation_run_id, content_brief_id, content_type, title, hook, body, call_to_action, affiliate_disclosure, claims, status, created_at, updated_at)
                VALUES ('source', 'generation', 'brief', 'ARTICLE', 'title', 'hook', 'body', 'CHECK_DETAILS', 'affiliate link disclosure', '[]'::json, 'GENERATED', now(), now())
            """))
            connection.execute(text("""
                INSERT INTO content_evaluations (id, artifact_id, content_brief_id, generation_run_id, factual_grounding_score, offer_alignment_score, intent_alignment_score, clarity_score, cta_score, compliance_score, overall_score, decision, approved, evaluator_version, policy_version, claim_results, compliance_flags, unsupported_claims, missing_evidence_ids, revision_reasons, rejection_reasons, created_at, updated_at)
                VALUES ('evaluation', 'source', 'brief', 'generation', 100, 100, 100, 100, 100, 100, 100, 'APPROVED', true, 'content-evaluator-v1', 'affiliate-content-policy-v1', '[]'::json, '[]'::json, '[]'::json, '[]'::json, '[]'::json, '[]'::json, now(), now())
            """))
            connection.execute(text("""
                INSERT INTO content_generation_runs (id, content_brief_id, idempotency_key, provider, model, prompt_version, generation_parameters, status, attempt_count, created_at, updated_at)
                VALUES ('variant-generation', 'brief', 'variant-generation', 'fake', 'fake', 'v1', '{}', 'COMPLETED', 1, now(), now())
            """))
            connection.execute(text("""
                INSERT INTO generated_content_artifacts (id, generation_run_id, content_brief_id, content_type, title, hook, body, call_to_action, affiliate_disclosure, claims, status, created_at, updated_at)
                VALUES ('result', 'variant-generation', 'brief', 'SOCIAL_POST', 'title', 'hook', 'body', 'CHECK_DETAILS', 'affiliate link disclosure', '[]'::json, 'GENERATED', now(), now())
            """))
            connection.execute(text("""
                INSERT INTO content_repurposing_runs (id, source_artifact_id, source_evaluation_id, generation_run_id, result_artifact_id, target_content_type, channel_intent, status, created_at, updated_at)
                VALUES ('repurposing', 'source', 'evaluation', 'variant-generation', 'result', 'SOCIAL_POST', 'SOCIAL', 'COMPLETED', now(), now())
            """))
            assert connection.execute(text("SELECT result_artifact_id FROM content_repurposing_runs WHERE id='repurposing'")) .scalar_one() == "result"
        inspector = inspect(engine)
        assert "content_repurposing_runs" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("content_repurposing_runs")}
        assert {"id", "source_artifact_id", "source_evaluation_id", "generation_run_id", "result_artifact_id", "target_content_type", "channel_intent", "status", "error_summary", "started_at", "completed_at", "created_at", "updated_at"}.issubset(columns)
        assert any(set(item["column_names"]) == {"generation_run_id"} for item in inspector.get_unique_constraints("content_repurposing_runs"))
        indexes = {item["name"] for item in inspector.get_indexes("content_repurposing_runs")}
        assert {"ix_content_repurposing_runs_source_artifact_id", "ix_content_repurposing_runs_source_evaluation_id", "ix_content_repurposing_runs_status", "ix_content_repurposing_runs_target_content_type"}.issubset(indexes)
        timestamp_columns = {column["name"]: column["type"].timezone for column in inspector.get_columns("content_repurposing_runs") if column["name"] in {"started_at", "completed_at", "created_at", "updated_at"}}
        assert timestamp_columns == {"started_at": True, "completed_at": True, "created_at": True, "updated_at": True}
    # Context exit above drops exactly the disposable database before this assertion.
    admin = create_engine(str(base_url.set(database="postgres")), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            assert database_name not in set(connection.execute(text("SELECT datname FROM pg_database")).scalars())
    finally:
        admin.dispose()
