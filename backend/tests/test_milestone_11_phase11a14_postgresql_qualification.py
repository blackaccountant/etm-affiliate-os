"""Guarded PostgreSQL qualification for M11A14 execution observation."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.distribution_run import DistributionRun
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.optimization.economic_recommendation_experiment_execution_binding_contracts import EconomicRecommendationExperimentExecutionBindingRow
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import EconomicRecommendationExperimentExecutionObservationPolicy, EconomicRecommendationExperimentExecutionObservationRequest
from app.services.economic_recommendation_experiment_execution_observation_service import EconomicRecommendationExperimentExecutionObservationService

DATABASE = "etm_g5_m11a14_execution_observation_qualification"
ROLE = os.getenv("ETM_G5_M11A14_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A14_DATABASE_URL")
FRESHNESS = os.getenv("ETM_G5_M11A14_DB_FRESHNESS_ATTESTED")

if not RAW:
    pytest.skip("requires guarded M11A14 URL", allow_module_level=True)
URL = make_url(RAW)
if (ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE or FRESHNESS not in {"1", "true", "True", "TRUE"}):
    raise RuntimeError("M11A14 database guard failed")

ENGINE = create_engine(URL.render_as_string(hide_password=False), future=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def _now():
    return datetime.now(timezone.utc)


def _binding_row(run_id):
    now = _now()
    return EconomicRecommendationExperimentExecutionBindingRow(
        experiment_reference="experiment-1", activation_reference="activation-1",
        distribution_run_id=run_id, actor_reference="actor-1", decision_reference="decision-1",
        authorized_at=now, design_reference="design-1", designed_at=now,
        hypothesis="hypothesis", control_definition="control", treatment_definition="treatment",
        success_measure="profit", observation_window=timedelta(days=7),
        recommendation_policy_version="recommendation-v1", approval_policy_version="approval-v1",
        experiment_design_policy_version="design-v1", activation_policy_version="activation-v1",
        source_experiment_design_semantics="design-semantics",
        source_experiment_design_contract_version="design-contract-v1",
        source_activation_semantics="activation-semantics",
        source_activation_contract_version="activation-contract-v1",
        successor_operation_spec=EconomicRecommendationExperimentExecutionBindingRow.established_distribution_publish_spec(run_id),
    )


def _persist_lineage(session, *, status, execution_ids=(1,)):
    """Persist the minimum FK-complete distribution lineage plus its operation."""
    token = uuid4().hex
    now = _now()
    discovery = DiscoveryRun(id=token + "d", input_type="KEYWORD", input_value="m11a14", input_data={}, status="COMPLETED", idempotency_key=token + "d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now, completed_at=now)
    session.add(discovery); session.flush()
    candidate = DiscoveryCandidate(id=token + "c", run_id=discovery.id, source_adapter="test", source_type="TEST", source_url=None, vendor_name="vendor", canonical_domain="example.test", offer_name="offer", program_name="program", affiliate_network=None, affiliate_url=None, program_identity_key=token + "p", dedupe_key=token + "k", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", confidence=100, score=100, created_at=now, updated_at=now)
    session.add(candidate); session.flush()
    brief = ContentBrief(id=token + "b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token + "b", status="READY", created_at=now, updated_at=now)
    session.add(brief); session.flush()
    generation = ContentGenerationRun(id=token + "g", content_brief_id=brief.id, idempotency_key=token + "g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
    session.add(generation); session.flush()
    artifact = GeneratedContentArtifact(id=token + "a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", claims=[], status="GENERATED", created_at=now, updated_at=now)
    session.add(artifact); session.flush()
    evaluation = ContentEvaluation(id=token + "e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)
    session.add(evaluation); session.flush()
    run = DistributionRun(id=token + "r", generated_content_artifact_id=artifact.id, content_evaluation_id=evaluation.id, platform="test", account_reference="account", destination="destination", status=status, publish_generation=0, reconciliation_generation=0, idempotency_key=token + "r", prepared_content_body="proof", payload_fingerprint="a" * 64, external_post_id="post" if status == "COMPLETED" else None, external_url="https://example.test/post" if status == "COMPLETED" else None, result_metadata={"source": "test"}, failure_category="UNKNOWN_PERMANENT" if status == "FAILED" else None, error_summary="failed" if status == "FAILED" else None, completed_at=now if status in {"COMPLETED", "FAILED"} else None, created_at=now, updated_at=now)
    session.add(run); session.flush()
    mission = MissionRecord(id=token + "m", name="ContentDistribution", objective="publish", workflow_name="distribution_publish", status="COMPLETED", input_data='{"distribution_run_id": "' + run.id + '"}', idempotency_key="distribution:" + run.id, result_data=None, last_error=None, created_at=now, updated_at=now, completed_at=now)
    session.add(mission); session.flush()
    for execution_id in execution_ids:
        session.add(Execution(id=execution_id, mission_id=mission.id, mission_name=mission.name, worker_name="worker", workflow_name="distribution_publish", status="COMPLETED", input_data=mission.input_data, result_data=None, started_at=now, completed_at=now))
    session.flush()
    return run, mission


def test_m11a14_requires_fresh_guarded_database():
    assert ROLE == "qualification" and URL.database == DATABASE
    with ENGINE.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none() == "c3d4e5f6a7b8"


@pytest.mark.parametrize("run_status, expected", [("COMPLETED", ("TERMINAL", "SUCCESS")), ("FAILED", ("TERMINAL", "FAILURE")), ("CANCELLED", ("TERMINAL", "FAILURE")), ("RECONCILIATION_REQUIRED", ("NON_TERMINAL", "UNRESOLVED"))])
def test_m11a14_observes_real_persisted_lineage(run_status, expected):
    with Session() as baseline:
        run, mission = _persist_lineage(baseline, status=run_status, execution_ids=(int(uuid4().int % 1000000000),))
        run_id, mission_id = run.id, mission.id
        baseline.commit()
    with Session() as session:
        before = (session.get(DistributionRun, run_id).status, session.get(MissionRecord, mission_id).status)
        observed = EconomicRecommendationExperimentExecutionObservationService(session).project(
            EconomicRecommendationExperimentExecutionObservationRequest((_binding_row(run_id),), EconomicRecommendationExperimentExecutionObservationPolicy("v1")),
        )[0]
        assert (observed.terminal_classification, observed.success_failure_classification) == expected
        assert observed.distribution_run_id == run_id and observed.mission_id == mission_id
        assert (session.get(DistributionRun, run_id).status, session.get(MissionRecord, mission_id).status) == before


def test_m11a14_uses_latest_execution_id_without_transaction_ownership():
    with Session() as baseline:
        first = int(uuid4().int % 400000000)
        run, mission = _persist_lineage(baseline, status="COMPLETED", execution_ids=(first, first + 1))
        run_id = run.id
        baseline.commit()
    session = Session()
    try:
        observed = EconomicRecommendationExperimentExecutionObservationService(session).project(
            EconomicRecommendationExperimentExecutionObservationRequest((_binding_row(run_id),), EconomicRecommendationExperimentExecutionObservationPolicy("v1")),
        )[0]
        assert observed.execution_id == first + 1
        session.rollback()
    finally:
        session.close()
