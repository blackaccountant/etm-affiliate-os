"""Guarded PostgreSQL qualification for M11A15 observation persistence."""

import os
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import EconomicRecommendationExperimentExecutionObservationRow
from app.optimization.economic_recommendation_experiment_observation_persistence_contracts import EconomicRecommendationExperimentObservationPersistencePolicy, EconomicRecommendationExperimentObservationPersistenceRequest
from app.services.economic_recommendation_experiment_observation_persistence_service import EconomicRecommendationExperimentObservationPersistenceService

DATABASE = "etm_g5_m11a15_observation_persistence_qualification"
ROLE = os.getenv("ETM_G5_M11A15_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A15_DATABASE_URL")
FRESHNESS = os.getenv("ETM_G5_M11A15_DB_FRESHNESS_ATTESTED")
if not RAW:
    pytest.skip("requires guarded M11A15 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE or FRESHNESS not in {"1", "true", "True", "TRUE"}:
    raise RuntimeError("M11A15 database guard failed")
ENGINE = create_engine(URL.render_as_string(hide_password=False), future=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def _now(): return datetime.now(timezone.utc)


def _source(run, mission, execution, *, status="COMPLETED"):
    now = _now()
    terminal, outcome = (("TERMINAL", "SUCCESS") if status == "COMPLETED" else ("NON_TERMINAL", "UNRESOLVED"))
    return EconomicRecommendationExperimentExecutionObservationRow(
        experiment_reference="experiment", activation_reference="activation", distribution_run_id=run.id,
        actor_reference="actor", decision_reference="decision", authorized_at=now, mission_id=mission.id,
        execution_id=execution.id, mission_status=mission.status, execution_status=execution.status,
        distribution_run_status=status, external_post_id="post", external_url="https://example.test/post",
        platform="test", account_reference="account", destination="destination", result_metadata={"v": status},
        failure_category=None, error_summary=None, distribution_run_completed_at=now,
        execution_completed_at=execution.completed_at, mission_completed_at=mission.completed_at,
        terminal_classification=terminal, success_failure_classification=outcome,
        execution_observation_policy_version="policy",
        execution_observation_contract_version="m11a14-economic-experiment-execution-observation-v1",
        execution_observation_semantics="consume exact frozen M11A12 execution-binding rows; deterministically resolve their M11A13 durable Mission through the established distribution mission idempotency key; read the canonical latest Execution using the established ExecutionRepository.get_by_mission_id() descending-ID ordering; read the referenced persisted DistributionRun; and emit an immutable deterministic execution/publication observation preserving experiment lineage. DistributionRun status is authoritative for publication outcome. No mutation, activation, scheduling, dispatch, publishing, attribution, scoring, winner selection, or economic inference.",
    )


def _lineage(session):
    token, now = uuid4().hex, _now()
    discovery = DiscoveryRun(id=token + "d", input_type="KEYWORD", input_value="m11a15", input_data={}, status="COMPLETED", idempotency_key=token + "d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now, completed_at=now); session.add(discovery); session.flush()
    candidate = DiscoveryCandidate(id=token + "c", run_id=discovery.id, source_adapter="test", source_type="TEST", source_url=None, vendor_name="vendor", canonical_domain="example.test", offer_name="offer", program_name="program", affiliate_network=None, affiliate_url=None, program_identity_key=token + "p", dedupe_key=token + "k", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", confidence=100, score=100, created_at=now, updated_at=now); session.add(candidate); session.flush()
    brief = ContentBrief(id=token + "b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token + "b", status="READY", created_at=now, updated_at=now); session.add(brief); session.flush()
    generation = ContentGenerationRun(id=token + "g", content_brief_id=brief.id, idempotency_key=token + "g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now); session.add(generation); session.flush()
    artifact = GeneratedContentArtifact(id=token + "a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", claims=[], status="GENERATED", created_at=now, updated_at=now); session.add(artifact); session.flush()
    evaluation = ContentEvaluation(id=token + "e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now); session.add(evaluation); session.flush()
    run = DistributionRun(id=token + "r", generated_content_artifact_id=artifact.id, content_evaluation_id=evaluation.id, platform="test", account_reference="account", destination="destination", status="COMPLETED", publish_generation=0, reconciliation_generation=0, idempotency_key=token + "r", prepared_content_body="proof", payload_fingerprint="a" * 64, created_at=now, updated_at=now); session.add(run); session.flush()
    mission = MissionRecord(id=token + "m", name="ContentDistribution", objective="publish", workflow_name="distribution_publish", status="COMPLETED", input_data=None, idempotency_key="distribution:" + run.id, current_worker_name=None, result_data=None, last_error=None, created_at=now, updated_at=now, completed_at=now); session.add(mission); session.flush()
    execution = Execution(mission_id=mission.id, mission_name=mission.name, worker_name="worker", workflow_name="distribution_publish", status="COMPLETED", started_at=now, completed_at=now); session.add(execution); session.flush()
    return run, mission, execution


def _request(source): return EconomicRecommendationExperimentObservationPersistenceRequest((source,), EconomicRecommendationExperimentObservationPersistencePolicy("v1"))


def test_m11a15_requires_fresh_guarded_database():
    with ENGINE.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none() == "d7e8f9a0b1c2"


def test_m11a15_table_constraints_and_indexes_exist():
    with ENGINE.begin() as connection:
        assert connection.execute(text("SELECT to_regclass('economic_recommendation_experiment_observations')")).scalar_one() is not None
        names = {row[0] for row in connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'economic_recommendation_experiment_observations'"))}
        assert {"ix_economic_experiment_observations_experiment", "ix_economic_experiment_observations_distribution_run", "ix_economic_experiment_observations_execution"}.issubset(names)
        constraints = {
            row[0]: row[1]
            for row in connection.execute(text("SELECT conname, contype FROM pg_constraint WHERE conrelid = 'economic_recommendation_experiment_observations'::regclass"))
        }
        assert constraints["uq_economic_experiment_observations_fingerprint"] == "u"
        execution_unique_indexes = connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'economic_recommendation_experiment_observations' AND indexdef LIKE 'CREATE UNIQUE INDEX%' AND indexdef LIKE '%(execution_id)%'"))
        assert execution_unique_indexes.all() == []
        execution_unique_constraints = connection.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = 'economic_recommendation_experiment_observations'::regclass AND contype = 'u' AND pg_get_constraintdef(oid) LIKE '%(execution_id)%'"))
        assert execution_unique_constraints.all() == []


def test_m11a15_persists_exact_snapshot_and_replays_idempotently():
    with Session() as session:
        run, mission, execution = _lineage(session); session.commit()
        source = _source(run, mission, execution)
        service = EconomicRecommendationExperimentObservationPersistenceService(session)
        first = service.persist(_request(source))[0]
        replay = service.persist(_request(source))[0]
        assert first.id == replay.id and first.result_metadata == source.result_metadata
        assert session.query(type(first)).filter_by(execution_id=execution.id).count() == 1


def test_m11a15_changed_same_execution_persists_distinct_snapshot_without_source_reread():
    with Session() as session:
        run, mission, execution = _lineage(session); session.commit()
        service = EconomicRecommendationExperimentObservationPersistenceService(session)
        first = service.persist(_request(_source(run, mission, execution, status="RECONCILIATION_REQUIRED")))[0]
        run.status = "FAILED"; session.commit()
        second = service.persist(_request(_source(run, mission, execution, status="COMPLETED")))[0]
        assert first.id != second.id and first.execution_id == second.execution_id
        assert first.distribution_run_status == "RECONCILIATION_REQUIRED" and second.distribution_run_status == "COMPLETED"
