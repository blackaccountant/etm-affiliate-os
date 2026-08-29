import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.content_intelligence.contracts import (
    ContentBriefStatus,
    ContentGenerationRunStatus,
    ContentType,
    EvidenceUsageRole,
)
from app.core.config import settings
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_content_asset import AffiliateContentAsset


if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip(
        "Requires a local disposable PostgreSQL database; set ETM_RUN_POSTGRES_INTEGRATION=1 to run.",
        allow_module_level=True,
    )


POSTGRES_URL = os.getenv("ETM_POSTGRES_INTEGRATION_URL")
if not POSTGRES_URL:
    raise RuntimeError("ETM_POSTGRES_INTEGRATION_URL must be set for the PostgreSQL migration gate.")

base_url = make_url(POSTGRES_URL)
if base_url.host != "127.0.0.1":
    raise RuntimeError("Phase 4B PostgreSQL migration gate requires host 127.0.0.1.")
if base_url.port != 5432:
    raise RuntimeError("Phase 4B PostgreSQL migration gate requires port 5432.")


@contextmanager
def disposable_phase4b_database():
    db_name = f"etm_phase4b_{uuid.uuid4().hex}"
    maint_url = base_url.set(database="postgres")
    admin_engine = create_engine(str(maint_url), isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        database_url = str(base_url.set(database=db_name))
        settings.DATABASE_URL = database_url

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(database_url, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        phase4b_db = SimpleNamespace(name=db_name, url=database_url, engine=engine, SessionLocal=SessionLocal)
        yield phase4b_db
    finally:
        try:
            if "engine" in locals():
                engine.dispose()
        except Exception:
            pass

        try:
            with admin_engine.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :db_name AND pid <> pg_backend_pid()"
                    ),
                    {"db_name": db_name},
                )
                conn.execute(text(f'DROP DATABASE "{db_name}"'))
        except Exception:
            pass
        finally:
            admin_engine.dispose()


@pytest.fixture(scope="module")
def postgres_phase4b_db():
    with disposable_phase4b_database() as phase4b_db:
        yield phase4b_db


def _assert_table_columns(engine, table_name, expected_columns):
    inspector = inspect(engine)
    actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing = sorted(set(expected_columns) - actual_columns)
    assert not missing, f"Missing columns in {table_name}: {missing}"


def _assert_no_columns(engine, table_name, forbidden_columns):
    inspector = inspect(engine)
    actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
    stale = sorted(set(forbidden_columns) & actual_columns)
    assert not stale, f"Unexpected stale columns in {table_name}: {stale}"


def _assert_fk_targets(engine, table_name, expected_fk_pairs):
    inspector = inspect(engine)
    actual_fks = inspector.get_foreign_keys(table_name)
    fk_map = {
        (fk["constrained_columns"][0], fk["referred_table"]): fk
        for fk in actual_fks
    }
    for constrained_column, referred_table in expected_fk_pairs:
        assert (constrained_column, referred_table) in fk_map, (
            f"Missing foreign key in {table_name}: {constrained_column} -> {referred_table}"
        )


def _assert_unique_column_group(engine, table_name, columns, unique_name=None):
    inspector = inspect(engine)
    for constraint in inspector.get_unique_constraints(table_name):
        if set(constraint.get("column_names", [])) == set(columns):
            if unique_name is not None:
                assert constraint.get("name") == unique_name
            return
    pytest.fail(f"Missing unique constraint on {table_name} for columns {columns}")


def _assert_index_names(engine, table_name, expected_names):
    inspector = inspect(engine)
    index_names = {idx["name"] for idx in inspector.get_indexes(table_name)}
    missing = sorted(set(expected_names) - index_names)
    assert not missing, f"Missing indexes in {table_name}: {missing}"


def test_postgres_migration_gate_and_schema(postgres_phase4b_db):
    database_url_parts = make_url(postgres_phase4b_db.url)
    assert database_url_parts.drivername.startswith("postgresql")
    assert database_url_parts.username == "postgres"
    assert database_url_parts.host == "127.0.0.1"
    assert database_url_parts.port == 5432
    assert database_url_parts.database.startswith("etm_phase4b_")
    assert database_url_parts.password is None
    assert postgres_phase4b_db.name.startswith("etm_phase4b_")

    engine = postgres_phase4b_db.engine
    SessionLocal = postgres_phase4b_db.SessionLocal
    database_url = postgres_phase4b_db.url
    db_name = postgres_phase4b_db.name

    with engine.connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        assert revision == "a1b2c3d4e5f6", f"Unexpected Alembic revision: {revision}"

        table_names = set(inspect(engine).get_table_names())
        for table_name in ["content_briefs", "content_brief_evidence", "content_generation_runs"]:
            assert table_name in table_names, f"Missing required table: {table_name}"

        brief_columns = {
            "id",
            "discovery_run_id",
            "discovery_candidate_id",
            "content_type",
            "channel_intent",
            "objective",
            "audience_intent",
            "audience_problem",
            "angle",
            "call_to_action",
            "tone",
            "required_disclosure",
            "key_benefits",
            "proof_points",
            "target_keywords",
            "constraints",
            "idempotency_key",
            "status",
            "created_at",
            "updated_at",
        }
        _assert_table_columns(engine, "content_briefs", brief_columns)
        _assert_no_columns(
            engine,
            "content_briefs",
            ["target_audience", "title", "primary_keyword", "secondary_keywords"],
        )
        _assert_fk_targets(
            engine,
            "content_briefs",
            [("discovery_run_id", "discovery_runs"), ("discovery_candidate_id", "discovery_candidates")],
        )
        _assert_unique_column_group(engine, "content_briefs", ["idempotency_key"], unique_name="uq_content_briefs_idempotency_key")
        _assert_index_names(
            engine,
            "content_briefs",
            [
                "ix_content_briefs_discovery_run_id",
                "ix_content_briefs_discovery_candidate_id",
                "ix_content_briefs_status",
                "ix_content_briefs_idempotency_key",
                "ix_content_briefs_candidate_run",
            ],
        )

        evidence_columns = {
            "id",
            "content_brief_id",
            "evidence_observation_id",
            "usage_role",
            "created_at",
        }
        _assert_table_columns(engine, "content_brief_evidence", evidence_columns)
        _assert_no_columns(
            engine,
            "content_brief_evidence",
            [
                "claim_type",
                "observed_value",
                "source_url",
                "source_type",
                "excerpt",
                "http_status",
                "content_hash",
                "extractor",
                "extractor_version",
                "confidence",
                "observed_at",
            ],
        )
        _assert_fk_targets(
            engine,
            "content_brief_evidence",
            [("content_brief_id", "content_briefs"), ("evidence_observation_id", "evidence_observations")],
        )
        _assert_unique_column_group(
            engine,
            "content_brief_evidence",
            ["content_brief_id", "evidence_observation_id", "usage_role"],
            unique_name="uq_content_brief_evidence_tuple",
        )
        _assert_index_names(
            engine,
            "content_brief_evidence",
            [
                "ix_content_brief_evidence_content_brief_id",
                "ix_content_brief_evidence_evidence_observation_id",
                "ix_content_brief_evidence_brief_usage",
            ],
        )

        generation_columns = {
            "id",
            "content_brief_id",
            "idempotency_key",
            "provider",
            "model",
            "prompt_version",
            "generation_parameters",
            "status",
            "attempt_count",
            "result_summary",
            "error_summary",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        }
        _assert_table_columns(engine, "content_generation_runs", generation_columns)
        _assert_no_columns(engine, "content_generation_runs", ["generated_content", "body"])
        _assert_fk_targets(engine, "content_generation_runs", [("content_brief_id", "content_briefs")])
        _assert_unique_column_group(engine, "content_generation_runs", ["idempotency_key"], unique_name="uq_content_generation_runs_idempotency_key")
        _assert_index_names(
            engine,
            "content_generation_runs",
            [
                "ix_content_generation_runs_content_brief_id",
                "ix_content_generation_runs_status",
                "ix_content_generation_runs_idempotency_key",
            ],
        )

        ts_columns = {
            "content_briefs": ["created_at", "updated_at"],
            "content_brief_evidence": ["created_at"],
            "content_generation_runs": ["started_at", "completed_at", "created_at", "updated_at"],
        }
        for table_name, columns in ts_columns.items():
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, udt_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :table_name AND column_name = ANY(:columns)"
                ),
                {"table_name": table_name, "columns": columns},
            ).mappings().all()
            assert rows, f"No timestamp metadata found for {table_name}"
            for row in rows:
                assert row["data_type"] in {"timestamp with time zone", "timestamp"} or row["udt_name"] in {"timestamptz", "timestamp"}

    session = SessionLocal()
    try:
        run = DiscoveryRun(
            id="run-4b-1",
            input_type="URL",
            input_value="https://example.com",
            status="CREATED",
            idempotency_key="run-4b-key-1",
            candidate_count=0,
            verified_count=0,
            selected_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        candidate = DiscoveryCandidate(
            id="candidate-4b-1",
            run_id="run-4b-1",
            source_adapter="official_site",
            source_type="affiliate_program",
            canonical_domain="example.com",
            program_identity_key="example:program:1",
            dedupe_key="example:program:1",
            commission_model="UNKNOWN",
            verification_status="VERIFIED",
            disposition="SELECTED",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        evidence = EvidenceObservation(
            id="evidence-4b-1",
            candidate_id="candidate-4b-1",
            claim_type="commission_rate",
            observed_value={"value": "12%"},
            source_url="https://example.com/affiliate",
            source_type="affiliate_program",
            extractor="official_site",
            extractor_version="v1",
            confidence=95,
            created_at=datetime.now(timezone.utc),
            observed_at=datetime.now(timezone.utc),
        )
        brief = ContentBrief(
            id="brief-4b-1",
            discovery_run_id="run-4b-1",
            discovery_candidate_id="candidate-4b-1",
            content_type=ContentType.ARTICLE.value,
            channel_intent="SEO",
            objective="Compare budget earbuds for value.",
            audience_intent="Shoppers comparing budget earbuds",
            audience_problem="They want value without overspending.",
            angle="Compare battery life, comfort, and price.",
            call_to_action="Read the guide and compare the top options.",
            tone="trustworthy",
            required_disclosure="This article includes affiliate links.",
            key_benefits=["clear comparison", "price transparency"],
            proof_points=["battery life", "comfort", "value"],
            target_keywords=["wireless earbuds", "best budget earbuds"],
            constraints=["No unsupported claims"],
            idempotency_key="brief-4b-key-1",
            status=ContentBriefStatus.READY.value,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        brief_link = ContentBriefEvidence(
            id="brief-evidence-4b-1",
            content_brief_id="brief-4b-1",
            evidence_observation_id="evidence-4b-1",
            usage_role=EvidenceUsageRole.PRIMARY.value,
            created_at=datetime.now(timezone.utc),
        )
        generation_run = ContentGenerationRun(
            id="gen-4b-1",
            content_brief_id="brief-4b-1",
            idempotency_key="gen-4b-key-1",
            provider="openai",
            model="gpt-4.1",
            prompt_version="v1",
            generation_parameters={"temperature": 0.2},
            status=ContentGenerationRunStatus.CREATED.value,
            attempt_count=0,
            result_summary="queued",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        session.add_all([run, candidate, evidence, brief, brief_link, generation_run])
        session.commit()

        assert session.query(Product).count() == 0
        assert session.query(AffiliateProgram).count() == 0
        assert session.query(AffiliateOpportunity).count() == 0
        assert session.query(AffiliateContentAsset).count() == 0

        round_trip_brief = session.query(ContentBrief).filter_by(id="brief-4b-1").one()
        assert round_trip_brief.audience_intent == "Shoppers comparing budget earbuds"
        assert round_trip_brief.audience_problem == "They want value without overspending."
        assert round_trip_brief.idempotency_key == "brief-4b-key-1"

        round_trip_link = session.query(ContentBriefEvidence).filter_by(id="brief-evidence-4b-1").one()
        assert round_trip_link.usage_role == EvidenceUsageRole.PRIMARY.value
        assert round_trip_link.evidence_observation_id == "evidence-4b-1"

        round_trip_generation = session.query(ContentGenerationRun).filter_by(id="gen-4b-1").one()
        assert round_trip_generation.content_brief_id == "brief-4b-1"
        assert round_trip_generation.provider == "openai"
        assert round_trip_generation.status == ContentGenerationRunStatus.CREATED.value
        assert round_trip_generation.created_at.tzinfo is not None
        assert round_trip_generation.updated_at.tzinfo is not None
        assert round_trip_brief.created_at.tzinfo is not None
        assert round_trip_brief.updated_at.tzinfo is not None

        session.commit()
    finally:
        session.close()


def test_cleanup_removes_exact_disposable_db():
    with disposable_phase4b_database() as phase4b_db:
        created_db_name = phase4b_db.name
        assert created_db_name.startswith("etm_phase4b_")

    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(str(admin_url), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            result = conn.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE 'etm_phase4b_%' ORDER BY datname")
            ).scalars().all()
        assert created_db_name not in result, f"Disposable DB {created_db_name} still exists after cleanup"
    finally:
        admin_engine.dispose()
