"""Guarded PostgreSQL qualification for M11A16 read-only evidence resolution."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.economic_recommendation_experiment_observation import EconomicRecommendationExperimentObservation
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.models.product import Product
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS,
    EconomicRecommendationExperimentExecutionObservationRow,
)
from app.optimization.economic_recommendation_experiment_observation_persistence_contracts import (
    EconomicRecommendationExperimentObservationPersistencePolicy,
    EconomicRecommendationExperimentObservationPersistenceRequest,
)
from app.services.affiliate_financial_adjustment_service import AffiliateFinancialAdjustmentService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.economic_recommendation_experiment_economic_evidence_service import EconomicRecommendationExperimentEconomicEvidenceService
from app.services.economic_recommendation_experiment_observation_persistence_service import EconomicRecommendationExperimentObservationPersistenceService
from app.optimization.economic_recommendation_experiment_economic_evidence_contracts import (
    EconomicRecommendationExperimentEconomicEvidencePolicy,
    EconomicRecommendationExperimentEconomicEvidenceRequest,
    NO_EVIDENCE,
    RESOLVED,
)


DATABASE = "etm_g5_m11a16_economic_evidence_qualification"
ROLE = os.getenv("ETM_G5_M11A16_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A16_DATABASE_URL")
FRESHNESS = os.getenv("ETM_G5_M11A16_DB_FRESHNESS_ATTESTED")
if not RAW:
    pytest.skip("requires guarded M11A16 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE or FRESHNESS not in {"1", "true", "True", "TRUE"}:
    raise RuntimeError("M11A16 database guard failed")
ENGINE = create_engine(URL.render_as_string(hide_password=False), future=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def _now(): return datetime.now(timezone.utc)


def _lineage(session):
    token, now = uuid4().hex, _now()
    discovery = DiscoveryRun(id=token + "d", input_type="KEYWORD", input_value="m11a16", input_data={}, status="COMPLETED", idempotency_key=token + "d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now); session.add(discovery); session.flush()
    candidate = DiscoveryCandidate(id=token + "c", run_id=discovery.id, source_adapter="test", source_type="TEST", source_url=None, vendor_name="vendor", canonical_domain="example.test", offer_name="offer", program_name="program", affiliate_network=None, affiliate_url=None, program_identity_key=token + "p", dedupe_key=token + "k", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", confidence=100, score=100, created_at=now, updated_at=now); session.add(candidate); session.flush()
    brief = ContentBrief(id=token + "b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token + "b", status="READY", created_at=now, updated_at=now); session.add(brief); session.flush()
    generation = ContentGenerationRun(id=token + "g", content_brief_id=brief.id, idempotency_key=token + "g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now); session.add(generation); session.flush()
    artifact = GeneratedContentArtifact(id=token + "a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", claims=[], status="GENERATED", created_at=now, updated_at=now); session.add(artifact); session.flush()
    evaluation = ContentEvaluation(id=token + "e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now); session.add(evaluation); session.flush()
    run = DistributionRun(id=token + "r", generated_content_artifact_id=artifact.id, content_evaluation_id=evaluation.id, platform="test", account_reference="account", destination="destination", status="COMPLETED", publish_generation=0, reconciliation_generation=0, idempotency_key=token + "r", prepared_content_body="proof", payload_fingerprint="a" * 64, created_at=now, updated_at=now); session.add(run); session.flush()
    mission = MissionRecord(id=token + "m", name="ContentDistribution", objective="publish", workflow_name="distribution_publish", status="COMPLETED", input_data=None, idempotency_key="distribution:" + run.id, current_worker_name=None, result_data=None, last_error=None, created_at=now, updated_at=now, completed_at=now); session.add(mission); session.flush()
    execution = Execution(mission_id=mission.id, mission_name=mission.name, worker_name="worker", workflow_name="distribution_publish", status="COMPLETED", started_at=now, completed_at=now); session.add(execution); session.flush()
    return run, mission, execution


def _observation(session, run, mission, execution, fingerprint):
    now = _now()
    source = EconomicRecommendationExperimentExecutionObservationRow("experiment", "activation", run.id, "actor", "decision", now, mission.id, execution.id, mission.status, execution.status, run.status, None, None, "test", "account", "destination", None, None, None, now, execution.completed_at, mission.completed_at, "TERMINAL", "SUCCESS", "policy", ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION, ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS)
    persisted = EconomicRecommendationExperimentObservationPersistenceService(session).persist(EconomicRecommendationExperimentObservationPersistenceRequest((source,), EconomicRecommendationExperimentObservationPersistencePolicy("v1")))[0]
    assert persisted.observation_fingerprint != fingerprint or fingerprint == persisted.observation_fingerprint
    return persisted


def _settled_for_run(session, run, currency, adjustment=Decimal("0")):
    token, now = uuid4().hex, _now()
    product = Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active"); session.add(product); session.flush()
    program = AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active"); session.add(program); session.flush()
    asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); session.add(asset); session.flush()
    publication = AttributionPublicationService(session).bind_distribution(run.id)
    context = AttributionContextService(session).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
    link = AttributionLinkBridgeService(session).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://example.test", content_asset_id=asset.id)
    result = AttributionConversionBridgeService(session).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, sale_amount=Decimal("1000.00"), currency=currency, commission_rate=Decimal("10"), metadata_json=None)
    earning_link = AttributionEarningLinkService(session).reconcile(attribution_fact_id=result["fact"].id)
    earning = result["earning"]
    payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=Decimal("100.00"), currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); session.add(payout); session.flush()
    earning.payout_id, earning.status = payout.id, "paid"
    session.add(AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=Decimal("100.00"), currency=currency, status="completed", provider="test", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now)); session.commit()
    settlement = AttributionPayoutSettlementLinkService(session).reconcile(attribution_earning_link_id=earning_link.id)
    if adjustment:
        AffiliateFinancialAdjustmentService(session).reconcile(earning_id=earning.id, program_id=program.id, conversion_id=result["conversion"].id, settlement_link_id=settlement.id, adjustment_type="REVERSAL", adjustment_amount=adjustment, currency=currency, effective_at=now, source_namespace="m11a16", source_event_digest=uuid4().hex * 2)


def test_m11a16_requires_fresh_guarded_database_and_no_schema_change():
    with ENGINE.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "d7e8f9a0b1c2"
        assert connection.execute(text("SELECT to_regclass('economic_recommendation_experiment_economic_evidences')")).scalar_one() is None


def test_m11a16_resolves_persisted_m11a15_observations_with_zero_and_multi_currency_without_writes():
    with Session() as writer:
        run, mission, execution = _lineage(writer); writer.commit()
        _settled_for_run(writer, run, "USD", Decimal("-100.00")); _settled_for_run(writer, run, "EUR")
        observation = _observation(writer, run, mission, execution, "unused"); writer.commit()
        before = (writer.query(EconomicRecommendationExperimentObservation).count(), writer.get(EconomicRecommendationExperimentObservation, observation.id).distribution_run_status)
    with Session() as loader:
        stored = loader.get(EconomicRecommendationExperimentObservation, observation.id)
        loader.expunge(stored)
    with Session() as projection:
        rows = EconomicRecommendationExperimentEconomicEvidenceService(projection).resolve(EconomicRecommendationExperimentEconomicEvidenceRequest((stored,), EconomicRecommendationExperimentEconomicEvidencePolicy("v1")))
        assert [(row.currency, row.net_realized_commission, row.evidence_resolution_classification) for row in rows] == [("EUR", Decimal("100.00"), RESOLVED), ("USD", Decimal("0.00"), RESOLVED)]
    with Session() as verify:
        assert (verify.query(EconomicRecommendationExperimentObservation).count(), verify.get(EconomicRecommendationExperimentObservation, observation.id).distribution_run_status) == before


def test_m11a16_missing_source_is_no_evidence_for_persisted_m11a15_observation():
    with Session() as session:
        run, mission, execution = _lineage(session); session.commit()
        observation = _observation(session, run, mission, execution, "unused"); session.commit()
    with Session() as loader:
        stored = loader.get(EconomicRecommendationExperimentObservation, observation.id)
        loader.expunge(stored)
    with Session() as projection:
        row = EconomicRecommendationExperimentEconomicEvidenceService(projection).resolve(EconomicRecommendationExperimentEconomicEvidenceRequest((stored,), EconomicRecommendationExperimentEconomicEvidencePolicy("v1")))[0]
        assert row.evidence_resolution_classification == NO_EVIDENCE and row.net_realized_commission is None and row.currency is None
