"""Guarded G5 roundtrip proof for additive M6.2A signal tables."""
import os
from contextlib import contextmanager
import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from uuid import uuid4
from app.core.config import settings
from app.distribution.contracts import CreateDistributionRunRequest, DistributionRunStatus
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.distribution_run_service import DistributionRunService

REVISION, PREVIOUS = "b6c2d3e4f5a6", "a6b1c2d3e4f5"
raw = os.getenv("ETM_G5_DATABASE_URL")
if not raw: pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw)
if not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == "etm_affiliate_os_g5_test"): raise RuntimeError("M6.2A migration proof requires guarded local G5 only.")
def revision(engine):
    with engine.connect() as connection: return MigrationContext.configure(connection).get_current_revision()
@contextmanager
def guarded(config):
    prior=settings.DATABASE_URL
    try: settings.DATABASE_URL=url.render_as_string(hide_password=False); yield
    finally: settings.DATABASE_URL=prior


def _create_representative_distribution_run(db):
    """Reuse the approved M5 lineage from phase 5B without workflow activation."""
    token = str(uuid4())
    now = datetime.now(timezone.utc)
    ids = {name: str(uuid4()) for name in ("discovery", "candidate", "brief", "generation", "artifact", "evaluation")}
    db.add(DiscoveryRun(id=ids["discovery"], input_type="URL", input_value=f"https://example.com/{token}", status="COMPLETED", idempotency_key=f"m62-discovery:{token}", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now))
    db.flush()
    db.add(DiscoveryCandidate(id=ids["candidate"], run_id=ids["discovery"], source_adapter="official", source_type="official", canonical_domain="example.com", program_identity_key=f"m62-program:{token}", dedupe_key=f"m62-dedupe:{token}", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentBrief(id=ids["brief"], discovery_run_id=ids["discovery"], discovery_candidate_id=ids["candidate"], content_type="ARTICLE", channel_intent="SEO", objective="facts", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=f"m62-brief:{token}", status="READY", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentGenerationRun(id=ids["generation"], content_brief_id=ids["brief"], idempotency_key=f"m62-generation:{token}", provider="fake", model="fake", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now))
    db.flush()
    db.add(GeneratedContentArtifact(id=ids["artifact"], generation_run_id=ids["generation"], content_brief_id=ids["brief"], content_type="ARTICLE", title="Representative M5 fixture", hook="Representative M5 fixture hook", body="Representative M5 DistributionRun fixture body.", call_to_action="CHECK_DETAILS", affiliate_disclosure="Affiliate disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now))
    db.flush()
    db.add(ContentEvaluation(id=ids["evaluation"], artifact_id=ids["artifact"], content_brief_id=ids["brief"], generation_run_id=ids["generation"], factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="content-evaluator-v1", policy_version="affiliate-content-policy-v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now))
    db.flush()
    return DistributionRunService(db).create(CreateDistributionRunRequest(generated_content_artifact_id=ids["artifact"], content_evaluation_id=ids["evaluation"], platform=" WordPress ", account_reference=" primary   site ", destination=" blog   /main "))


def _distribution_run_snapshot(run):
    return (
        run.id,
        run.status,
        run.generated_content_artifact_id,
        run.content_evaluation_id,
        run.platform,
        run.account_reference,
        run.destination,
        run.idempotency_key,
        run.payload_fingerprint,
        run.prepared_content_body,
        run.scheduled_for,
        run.publish_generation,
        run.reconciliation_generation,
    )


def test_representative_distribution_run_fixture_persists_at_b6():
    engine = create_engine(url.render_as_string(hide_password=False))
    factory = sessionmaker(bind=engine)
    try:
        assert revision(engine) == REVISION
        db = factory()
        try:
            run = _create_representative_distribution_run(db)
            snapshot = _distribution_run_snapshot(run)
            run_id = run.id
        finally:
            db.close()
        db = factory()
        try:
            stored = db.get(DistributionRun, run_id)
            assert stored is not None
            assert stored.id == run_id
            assert stored.status == DistributionRunStatus.CREATED.value
            assert _distribution_run_snapshot(stored) == snapshot
        finally:
            db.close()
        assert revision(engine) == REVISION
    finally:
        engine.dispose()


def test_signal_roundtrip_preserves_m6_1_tables():
    config=Config("alembic.ini"); config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False)); engine=create_engine(url.render_as_string(hide_password=False))
    try:
        assert revision(engine) == REVISION
        tables=set(inspect(engine).get_table_names()); assert {"audience_signals", "audience_signal_evidence", "audience_evidence", "audience_observations"} <= tables
        db=sessionmaker(bind=engine)()
        try:
            service=AudienceFoundationService(db); token=str(uuid4()); run=service.get_or_create_research_run(scope_type="proof", scope_reference=token, idempotency_key="m62-proof:"+token); subject=service.create_subject("PERSON"); identity=service.attach_external_identity(subject.id, source_namespace="proof", identity_type="account", reference=token); observation=service.ingest_observation(research_run_id=run.id, subject_id=subject.id, source_namespace="proof", source_type="MANUAL", external_observation_id=token, source_reference=token, observed_at=datetime.now(timezone.utc), normalized_fact={"proof": token}); evidence=service.record_evidence(observation_id=observation.id, source_reference=token, normalized_representation={"proof": token}, content_fingerprint="a"*64); db.commit(); snapshot=(run.id, subject.id, identity.id, identity.normalized_reference, observation.id, observation.observation_key, evidence.id, evidence.evidence_fingerprint, evidence.content_fingerprint); distribution_snapshot=_distribution_run_snapshot(_create_representative_distribution_run(db))
        finally: db.close()
        with guarded(config): command.downgrade(config, PREVIOUS)
        assert revision(engine) == PREVIOUS
        tables=set(inspect(engine).get_table_names()); assert "audience_signals" not in tables and "audience_signal_evidence" not in tables and "audience_evidence" in tables
        db=sessionmaker(bind=engine)()
        try:
            distribution_run=db.get(DistributionRun, distribution_snapshot[0]); assert distribution_run is not None and _distribution_run_snapshot(distribution_run) == distribution_snapshot
        finally: db.close()
        with engine.connect() as connection:
            row=connection.execute(__import__("sqlalchemy").text("SELECT r.id,s.id,i.id,i.normalized_reference,o.id,o.observation_key,e.id,e.evidence_fingerprint,e.content_fingerprint FROM audience_research_runs r JOIN audience_observations o ON o.research_run_id=r.id JOIN audience_subjects s ON s.id=o.subject_id JOIN audience_external_identities i ON i.subject_id=s.id JOIN audience_evidence e ON e.observation_id=o.id WHERE r.id=:id"), {"id": snapshot[0]}).one(); assert tuple(row)==snapshot
        with guarded(config): command.upgrade(config, REVISION)
        assert revision(engine) == REVISION
        db=sessionmaker(bind=engine)()
        try:
            distribution_run=db.get(DistributionRun, distribution_snapshot[0]); assert distribution_run is not None and _distribution_run_snapshot(distribution_run) == distribution_snapshot
        finally: db.close()
        with engine.connect() as connection:
            row=connection.execute(__import__("sqlalchemy").text("SELECT r.id,s.id,i.id,i.normalized_reference,o.id,o.observation_key,e.id,e.evidence_fingerprint,e.content_fingerprint FROM audience_research_runs r JOIN audience_observations o ON o.research_run_id=r.id JOIN audience_subjects s ON s.id=o.subject_id JOIN audience_external_identities i ON i.subject_id=s.id JOIN audience_evidence e ON e.observation_id=o.id WHERE r.id=:id"), {"id": snapshot[0]}).one(); assert tuple(row)==snapshot
    finally: engine.dispose()
