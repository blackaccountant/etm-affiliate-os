"""Guarded local PostgreSQL roundtrip proof for operation generations."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact


REVISION = "fa1b2c3d4e5f"
PREVIOUS = "f9a0b1c2d3e4"
raw = os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw)
if url.host != "127.0.0.1" or url.port != 5432 or url.database != "etm_affiliate_os_g5_test":
    raise RuntimeError("Phase 5E.2C migration proof requires only guarded local G5.")


def revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def representative(engine):
    ids = {name: str(uuid4()) for name in ("discovery", "candidate", "brief", "generation", "artifact", "evaluation", "run")}
    now = datetime.now(timezone.utc)
    db = sessionmaker(bind=engine)()
    try:
        layers = [
            [DiscoveryRun(id=ids["discovery"], input_type="URL", input_value="https://example.invalid", status="COMPLETED", idempotency_key=ids["discovery"], candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)],
            [DiscoveryCandidate(id=ids["candidate"], run_id=ids["discovery"], source_adapter="test", source_type="test", canonical_domain="example.invalid", program_identity_key=ids["candidate"], dedupe_key=ids["candidate"], commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)],
            [ContentBrief(id=ids["brief"], discovery_run_id=ids["discovery"], discovery_candidate_id=ids["candidate"], content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=ids["brief"], status="READY", created_at=now, updated_at=now)],
            [ContentGenerationRun(id=ids["generation"], content_brief_id=ids["brief"], idempotency_key=ids["generation"], provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)],
            [GeneratedContentArtifact(id=ids["artifact"], generation_run_id=ids["generation"], content_brief_id=ids["brief"], content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now)],
            [ContentEvaluation(id=ids["evaluation"], artifact_id=ids["artifact"], content_brief_id=ids["brief"], generation_run_id=ids["generation"], factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)],
            [DistributionRun(id=ids["run"], generated_content_artifact_id=ids["artifact"], content_evaluation_id=ids["evaluation"], platform="test", account_reference="account", destination="destination", status="CREATED", idempotency_key=ids["run"], payload_fingerprint="a" * 64, prepared_content_body="proof body", created_at=now, updated_at=now)],
        ]
        for layer in layers:
            db.add_all(layer); db.flush()
        db.commit()
        return ids["run"], {"platform": "test", "account_reference": "account", "destination": "destination", "status": "CREATED", "idempotency_key": ids["run"], "payload_fingerprint": "a" * 64, "prepared_content_body": "proof body"}
    finally: db.close()


def test_operation_generation_roundtrip():
    config = Config("alembic.ini")
    value = url.render_as_string(hide_password=False)
    previous_setting = settings.DATABASE_URL
    engine = create_engine(value, pool_pre_ping=True)
    try:
        settings.DATABASE_URL = value
        command.upgrade(config, "head")
        columns = {column["name"]: column for column in inspect(engine).get_columns("distribution_runs")}
        assert revision(engine) == REVISION
        assert columns["publish_generation"]["nullable"] is False
        assert columns["reconciliation_generation"]["nullable"] is False
        row_id, expected = representative(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT publish_generation, reconciliation_generation FROM distribution_runs WHERE id=:id"), {"id": row_id}).one() == (0, 0)
        command.downgrade(config, PREVIOUS)
        columns = {column["name"] for column in inspect(engine).get_columns("distribution_runs")}
        assert {"publish_generation", "reconciliation_generation"}.isdisjoint(columns)
        assert {"missions", "workers", "executions", "distribution_runs"}.issubset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert dict(connection.execute(text("SELECT platform, account_reference, destination, status, idempotency_key, payload_fingerprint, prepared_content_body FROM distribution_runs WHERE id=:id"), {"id": row_id}).mappings().one()) == expected
        command.upgrade(config, "head")
        assert revision(engine) == REVISION
        with engine.connect() as connection:
            row = connection.execute(text("SELECT platform, account_reference, destination, status, idempotency_key, payload_fingerprint, prepared_content_body, publish_generation, reconciliation_generation FROM distribution_runs WHERE id=:id"), {"id": row_id}).mappings().one()
        assert {key: row[key] for key in expected} == expected and (row["publish_generation"], row["reconciliation_generation"]) == (0, 0)
    finally:
        settings.DATABASE_URL = previous_setting
        engine.dispose()
