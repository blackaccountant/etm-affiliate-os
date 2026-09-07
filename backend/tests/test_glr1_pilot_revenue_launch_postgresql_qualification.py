"""Guarded PostgreSQL qualification for GLR1 pre-publication launch binding."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.distribution.pilot_revenue_launch_contracts import PilotRevenueLaunchRequest
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.services.pilot_revenue_launch_service import PilotRevenueLaunchService


DATABASE = "etm_g5_glr1_pilot_revenue_launch_qualification"
ROLE, RAW, FRESHNESS = os.getenv("ETM_G5_GLR1_DB_ROLE"), os.getenv("ETM_G5_GLR1_DATABASE_URL"), os.getenv("ETM_G5_GLR1_DB_FRESHNESS_ATTESTED")
if not RAW:
    pytest.skip("requires guarded GLR1 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE or FRESHNESS not in {"1", "true", "True", "TRUE"}:
    raise RuntimeError("GLR1 database guard failed")
ENGINE = create_engine(URL.render_as_string(hide_password=False), future=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def _now(): return datetime.now(timezone.utc)


def _records(db):
    token, now = uuid4().hex, _now()
    discovery = DiscoveryRun(id=token+"d", input_type="URL", input_value="https://example.test", input_data={}, status="COMPLETED", idempotency_key=token+"d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now); db.add(discovery); db.flush()
    candidate = DiscoveryCandidate(id=token+"c", run_id=discovery.id, source_adapter="test", source_type="TEST", source_url=None, vendor_name="vendor", canonical_domain="example.test", offer_name="offer", program_name="program", affiliate_network=None, affiliate_url=None, program_identity_key=token+"p", dedupe_key=token+"k", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", confidence=100, score=100, created_at=now, updated_at=now); db.add(candidate); db.flush()
    brief = ContentBrief(id=token+"b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token+"b", status="READY", created_at=now, updated_at=now); db.add(brief); db.flush()
    generation = ContentGenerationRun(id=token+"g", content_brief_id=brief.id, idempotency_key=token+"g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now); db.add(generation); db.flush()
    artifact = GeneratedContentArtifact(id=token+"a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="body", call_to_action="CHECK_DETAILS", affiliate_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", claims=[], status="GENERATED", created_at=now, updated_at=now); db.add(artifact); db.flush()
    evaluation = ContentEvaluation(id=token+"e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now); db.add(evaluation)
    product = Product(name=token, website=f"https://{token}.example.test", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active"); db.add(product); db.flush()
    program = AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active"); db.add(program); db.flush()
    link = AffiliateLink(affiliate_program_id=program.id, name="pilot", destination_url="https://provider.test/offer", tracking_code=token, is_active=True); db.add(link); db.commit()
    return artifact.id, evaluation.id, link.id, link.tracking_code


def _request(artifact_id, evaluation_id, link_id, **changes):
    values = dict(artifact_id=artifact_id, evaluation_id=evaluation_id, platform="cms", account_reference="pilot", destination="/pilot", affiliate_link_id=link_id, prepared_content_body=None, scheduled_for=None)
    values.update(changes)
    return PilotRevenueLaunchRequest(**values)


def test_glr1_requires_fresh_database_and_no_glr1_table():
    with ENGINE.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "d7e8f9a0b1c2"
        assert connection.execute(text("SELECT to_regclass('pilot_revenue_launches')")).scalar_one() is None


def test_glr1_launches_and_replays_exact_durable_lineage():
    with Session() as db:
        artifact_id, evaluation_id, link_id, tracking_code = _records(db)
        first = PilotRevenueLaunchService(db).launch(_request(artifact_id, evaluation_id, link_id))
        assert first.tracking_code == tracking_code and first.public_redirect_path == f"/affiliate-links/go/{tracking_code}"
    with Session() as db:
        second = PilotRevenueLaunchService(db).launch(_request(artifact_id, evaluation_id, link_id))
        assert second == first
        assert db.query(DistributionRun).count() == 1
        assert db.query(AttributionPublication).count() == 1
        assert db.query(AttributionContext).count() == 1
        assert db.get(AffiliateLink, link_id).attribution_context_id == first.attribution_context_id


def test_glr1_rejects_different_context_replay_without_compensation():
    with Session() as db:
        before_runs = db.query(DistributionRun).count()
        before_publications = db.query(AttributionPublication).count()
        before_contexts = db.query(AttributionContext).count()
        artifact_id, evaluation_id, link_id, _ = _records(db)
        first = PilotRevenueLaunchService(db).launch(_request(artifact_id, evaluation_id, link_id))
        assert db.query(DistributionRun).count() == before_runs + 1
        assert db.query(AttributionPublication).count() == before_publications + 1
        assert db.query(AttributionContext).count() == before_contexts + 1
        with pytest.raises(AttributionBridgeConflict):
            PilotRevenueLaunchService(db).launch(_request(artifact_id, evaluation_id, link_id, destination="/other"))
        assert db.query(DistributionRun).count() == before_runs + 1
        assert db.query(AttributionPublication).count() == before_publications + 1
        assert db.query(AttributionContext).count() == before_contexts + 1
        assert db.get(AffiliateLink, link_id).attribution_context_id == first.attribution_context_id
