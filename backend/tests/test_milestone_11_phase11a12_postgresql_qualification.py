"""Guarded PostgreSQL qualification for M11A12 execution binding."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
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
from app.models.worker import Worker
from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS,
    EconomicRecommendationExperimentExecutionBinding,
    EconomicRecommendationExperimentExecutionBindingPolicy,
    EconomicRecommendationExperimentExecutionBindingRequest,
)
from app.optimization.economic_recommendation_experiment_activation_contracts import (
    EconomicRecommendationExperimentActivationRow,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.economic_recommendation_experiment_execution_binding_service import (
    EconomicRecommendationExperimentExecutionBindingService,
)

DATABASE = "etm_g5_m11a12_execution_binding_qualification"
ROLE = os.getenv("ETM_G5_M11A12_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A12_DATABASE_URL")
FRESHNESS = os.getenv("ETM_G5_M11A12_DB_FRESHNESS_ATTESTED")

if not RAW:
    pytest.skip("requires guarded M11A12 URL", allow_module_level=True)

URL = make_url(RAW)

if (
    ROLE != "qualification"
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != DATABASE
    or not FRESHNESS
):
    raise RuntimeError("M11A12 database guard failed")

ENGINE = create_engine(URL.render_as_string(hide_password=False))
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


class _StubActivationService:
    def __init__(self, rows):
        self.rows = tuple(rows)

    def project(self, request):
        return self.rows


def _now():
    return datetime.now(timezone.utc)


def _session():
    return Session()


def _activation_row(
    *,
    activation_reference="activation-1",
    distribution_run_id="run-1",
):
    return EconomicRecommendationExperimentActivationRow(
        experiment_reference="experiment-1",
        activation_reference=activation_reference,
        hypothesis="treatment improves operating profit",
        control_definition="retain current allocation",
        treatment_definition="apply approved treatment",
        success_measure="operating profit",
        observation_window=timedelta(days=7),
        actor_reference="activation-actor",
        decision_reference="activation-decision-1",
        authorized_at=_now() + timedelta(minutes=1),
        design_reference="design-1",
        designed_at=_now(),
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        experiment_design_policy_version="design-v1",
        activation_policy_version="activation-v1",
        source_experiment_design_semantics="design-semantics",
        source_experiment_design_contract_version="design-contract-v1",
    )


def _distribution_run(db, *, run_id=None):
    run_id = run_id or str(uuid4())
    now = _now()
    brief_id = str(uuid4())
    generation_id = str(uuid4())
    artifact_id = str(uuid4())
    evaluation_id = str(uuid4())
    discovery_run_id = str(uuid4())
    discovery_candidate_id = str(uuid4())

    db.add(
        DiscoveryRun(
            id=discovery_run_id,
            input_type="KEYWORD",
            input_value="m11a12 qualification",
            input_data={},
            status="COMPLETED",
            idempotency_key=f"discovery-run-{discovery_run_id}",
            candidate_count=1,
            verified_count=1,
            selected_count=1,
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    db.flush()

    db.add(
        DiscoveryCandidate(
            id=discovery_candidate_id,
            run_id=discovery_run_id,
            source_adapter="m11a12-qualification",
            source_type="TEST",
            source_url=None,
            vendor_name="qualification vendor",
            canonical_domain="qualification.example",
            offer_name="qualification offer",
            program_name="qualification program",
            affiliate_network=None,
            affiliate_url=None,
            program_identity_key=f"program-{discovery_candidate_id}",
            dedupe_key=f"candidate-{discovery_candidate_id}",
            commission_model="UNKNOWN",
            verification_status="VERIFIED",
            disposition="SELECTED",
            confidence=100,
            score=100,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()

    db.add(
        ContentBrief(
            id=brief_id,
            discovery_run_id=discovery_run_id,
            discovery_candidate_id=discovery_candidate_id,
            content_type="ARTICLE",
            channel_intent="SEO",
            objective="proof",
            call_to_action="CHECK_DETAILS",
            required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED",
            key_benefits=[],
            proof_points=[],
            target_keywords=[],
            constraints=[],
            idempotency_key=f"brief-{brief_id}",
            status="READY",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()

    db.add(
        ContentGenerationRun(
            id=generation_id,
            content_brief_id=brief_id,
            idempotency_key=f"generation-{generation_id}",
            provider="test",
            model="test",
            prompt_version="v1",
            generation_parameters={},
            status="COMPLETED",
            attempt_count=1,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()

    db.add(
        GeneratedContentArtifact(
            id=artifact_id,
            generation_run_id=generation_id,
            content_brief_id=brief_id,
            content_type="ARTICLE",
            title="proof",
            hook="proof",
            body="proof",
            call_to_action="CHECK_DETAILS",
            affiliate_disclosure="disclosure",
            claims=[],
            status="GENERATED",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()

    db.add(
        ContentEvaluation(
            id=evaluation_id,
            artifact_id=artifact_id,
            content_brief_id=brief_id,
            generation_run_id=generation_id,
            factual_grounding_score=100,
            offer_alignment_score=100,
            intent_alignment_score=100,
            clarity_score=100,
            cta_score=100,
            compliance_score=100,
            overall_score=100,
            decision="APPROVED",
            approved=True,
            evaluator_version="v1",
            policy_version="v1",
            claim_results=[],
            compliance_flags=[],
            unsupported_claims=[],
            missing_evidence_ids=[],
            revision_reasons=[],
            rejection_reasons=[],
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    row = DistributionRun(
        id=run_id,
        generated_content_artifact_id=artifact_id,
        content_evaluation_id=evaluation_id,
        platform="test",
        account_reference="account",
        destination="destination",
        status="CREATED",
        idempotency_key=f"run-{run_id}",
        payload_fingerprint="a" * 64,
        prepared_content_body="proof",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _durable_counts(db):
    return {
        "missions": db.query(MissionRecord).count(),
        "executions": db.query(Execution).count(),
        "workers": db.query(Worker).count(),
        "distribution_runs": db.query(DistributionRun).count(),
    }


def test_current_head_requires_no_m11a12_migration():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally:
        db.close()


def test_binding_binds_valid_activation_to_existing_distribution_run_and_emits_stable_spec():
    db = _session()
    try:
        run = _distribution_run(db)
        baseline = _durable_counts(db)
        activation = _activation_row(activation_reference="activation-1")
        request = EconomicRecommendationExperimentExecutionBindingRequest(
            experiment_activation_request=object(),
            execution_bindings=(
                EconomicRecommendationExperimentExecutionBinding(
                    activation_reference="activation-1",
                    distribution_run_id=run.id,
                ),
            ),
            execution_binding_policy=EconomicRecommendationExperimentExecutionBindingPolicy(
                "execution-binding-v1"
            ),
        )
        service = EconomicRecommendationExperimentExecutionBindingService(
            db,
            activation_service=_StubActivationService((activation,)),
            distribution_run_repository=DistributionRunRepository(db),
        )

        result = service.project(request)
        assert len(result) == 1
        row = result[0]
        assert row.activation_reference == "activation-1"
        assert row.distribution_run_id == run.id
        assert row.successor_operation_spec.name == "ContentDistribution"
        assert row.successor_operation_spec.workflow == "distribution_publish"
        assert row.successor_operation_spec.required_capability == "content_distribution"
        assert row.successor_operation_spec.idempotency_key == f"distribution:{run.id}"
        assert row.successor_operation_spec.payload == {"distribution_run_id": run.id}
        assert row.execution_binding_semantics == ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS

        refreshed = db.get(DistributionRun, run.id)
        assert refreshed.status == "CREATED"
        assert refreshed.updated_at == run.updated_at
        assert _durable_counts(db) == baseline
    finally:
        db.close()


def test_binding_does_not_create_runtime_activation_side_effects():
    db = _session()
    try:
        run = _distribution_run(db)
        before = _durable_counts(db)
        request = EconomicRecommendationExperimentExecutionBindingRequest(
            experiment_activation_request=object(),
            execution_bindings=(
                EconomicRecommendationExperimentExecutionBinding(
                    activation_reference="activation-2",
                    distribution_run_id=run.id,
                ),
            ),
            execution_binding_policy=EconomicRecommendationExperimentExecutionBindingPolicy(
                "execution-binding-v1"
            ),
        )
        service = EconomicRecommendationExperimentExecutionBindingService(
            db,
            activation_service=_StubActivationService((_activation_row(activation_reference="activation-2"),)),
            distribution_run_repository=DistributionRunRepository(db),
        )

        result = service.project(request)
        assert len(result) == 1
        assert result[0].successor_operation_spec.payload == {"distribution_run_id": run.id}
        after = _durable_counts(db)
        assert after == before
        assert db.query(MissionRecord).count() == 0
        assert db.query(Execution).count() == 0
        assert db.query(Worker).count() == 0
        db.execute(text("SELECT 1"))
    finally:
        db.close()
