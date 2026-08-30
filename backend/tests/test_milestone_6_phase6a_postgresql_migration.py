"""Guarded local-G5 roundtrip proof for the additive M6.1 migration."""

import os
from contextlib import contextmanager
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


REVISION = "a6b1c2d3e4f5"
PREVIOUS = "fa1b2c3d4e5f"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("M6.1 migration proof requires guarded local G5 only.")


def _revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


@contextmanager
def _guarded_alembic(config):
    previous = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = _url.render_as_string(hide_password=False)
        yield
    finally:
        settings.DATABASE_URL = previous


def _representative_distribution(engine):
    ids = {name: str(uuid4()) for name in ("discovery", "candidate", "brief", "generation", "artifact", "evaluation", "run")}
    now = datetime.now(timezone.utc)
    db = sessionmaker(bind=engine)()
    try:
        rows = [
            DiscoveryRun(id=ids["discovery"], input_type="URL", input_value="https://example.invalid", status="COMPLETED", idempotency_key=ids["discovery"], candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now),
            DiscoveryCandidate(id=ids["candidate"], run_id=ids["discovery"], source_adapter="test", source_type="test", canonical_domain="example.invalid", program_identity_key=ids["candidate"], dedupe_key=ids["candidate"], commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now),
            ContentBrief(id=ids["brief"], discovery_run_id=ids["discovery"], discovery_candidate_id=ids["candidate"], content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=ids["brief"], status="READY", created_at=now, updated_at=now),
            ContentGenerationRun(id=ids["generation"], content_brief_id=ids["brief"], idempotency_key=ids["generation"], provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now),
            GeneratedContentArtifact(id=ids["artifact"], generation_run_id=ids["generation"], content_brief_id=ids["brief"], content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now),
            ContentEvaluation(id=ids["evaluation"], artifact_id=ids["artifact"], content_brief_id=ids["brief"], generation_run_id=ids["generation"], factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now),
            DistributionRun(id=ids["run"], generated_content_artifact_id=ids["artifact"], content_evaluation_id=ids["evaluation"], platform="test", account_reference="account", destination="destination", status="CREATED", idempotency_key=ids["run"], payload_fingerprint="a" * 64, prepared_content_body="proof body", created_at=now, updated_at=now),
        ]
        for row in rows:
            db.add(row)
            db.flush()
        db.commit()
        return ids["run"]
    finally:
        db.close()


def test_audience_foundation_roundtrip_preserves_m5_distribution_data():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _url.render_as_string(hide_password=False))
    engine = create_engine(_url.render_as_string(hide_password=False), pool_pre_ping=True)
    try:
        assert _revision(engine) == PREVIOUS
        run_id = _representative_distribution(engine)
        with _guarded_alembic(config):
            command.upgrade(config, "head")
        assert _revision(engine) == REVISION
        tables = set(inspect(engine).get_table_names())
        assert {"audience_research_runs", "audience_subjects", "audience_external_identities", "audience_observations", "audience_evidence"} <= tables
        inspector = inspect(engine)
        assert "uq_audience_research_runs_idempotency_key" in {
            item["name"] for item in inspector.get_unique_constraints("audience_research_runs")
        }
        assert "uq_audience_external_identity_reference" in {
            item["name"] for item in inspector.get_unique_constraints("audience_external_identities")
        }
        assert "uq_audience_observations_key" in {
            item["name"] for item in inspector.get_unique_constraints("audience_observations")
        }
        assert "uq_audience_evidence_observation_fingerprint" in {
            item["name"] for item in inspector.get_unique_constraints("audience_evidence")
        }
        with engine.connect() as connection:
            assert connection.execute(text("SELECT status FROM distribution_runs WHERE id=:id"), {"id": run_id}).scalar_one() == "CREATED"

        with _guarded_alembic(config):
            command.downgrade(config, PREVIOUS)
        assert _revision(engine) == PREVIOUS
        tables = set(inspect(engine).get_table_names())
        assert not {"audience_research_runs", "audience_subjects", "audience_external_identities", "audience_observations", "audience_evidence"} & tables
        with engine.connect() as connection:
            row = connection.execute(text("SELECT platform, status, payload_fingerprint, prepared_content_body FROM distribution_runs WHERE id=:id"), {"id": run_id}).mappings().one()
        assert dict(row) == {"platform": "test", "status": "CREATED", "payload_fingerprint": "a" * 64, "prepared_content_body": "proof body"}

        with _guarded_alembic(config):
            command.upgrade(config, "head")
        assert _revision(engine) == REVISION
    finally:
        engine.dispose()
