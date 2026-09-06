"""Guarded PostgreSQL qualification for M11A13 durable activation."""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_WORKFLOW,
    distribution_mission_idempotency_key,
)
from app.mission.status import MissionStatus
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.optimization.economic_recommendation_experiment_durable_activation_contracts import (
    EconomicRecommendationExperimentDurableActivationPolicy,
    EconomicRecommendationExperimentDurableActivationRequest,
)
from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    EconomicRecommendationExperimentExecutionBindingRow,
)
from app.services.durable_operation_activation_service import OperationActivationState
from app.services.economic_recommendation_experiment_durable_activation_service import (
    EconomicRecommendationExperimentDurableActivationService,
)
from app.workforce.status import WorkerStatus

DATABASE = "etm_g5_m11a13_durable_activation_qualification"
ROLE = os.getenv("ETM_G5_M11A13_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A13_DATABASE_URL")
FRESHNESS = os.getenv("ETM_G5_M11A13_DB_FRESHNESS_ATTESTED")

if not RAW:
    pytest.skip("requires guarded M11A13 URL", allow_module_level=True)

URL = make_url(RAW)

if (
    ROLE != "qualification"
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != DATABASE
    or FRESHNESS not in {"1", "true", "True", "TRUE"}
):
    raise RuntimeError("M11A13 database guard failed")

ENGINE = create_engine(URL.render_as_string(hide_password=False), future=True)
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    with Session() as session:
        session.execute(text("DELETE FROM executions"))
        session.execute(text("DELETE FROM missions"))
        session.execute(text("DELETE FROM workers"))
        session.commit()
    yield
    with Session() as session:
        session.execute(text("DELETE FROM executions"))
        session.execute(text("DELETE FROM missions"))
        session.execute(text("DELETE FROM workers"))
        session.commit()


def _now():
    return datetime.now(timezone.utc)


def _unique_worker_name():
    return f"content-distribution-{uuid4().hex[:8]}"


def _binding_row(*, run_id: str = "run-1", activation_reference: str = "activation-1"):
    return EconomicRecommendationExperimentExecutionBindingRow(
        experiment_reference="experiment-1",
        activation_reference=activation_reference,
        distribution_run_id=run_id,
        actor_reference="activation-actor",
        decision_reference="activation-decision-1",
        authorized_at=_now() + timedelta(minutes=1),
        design_reference="design-1",
        designed_at=_now(),
        hypothesis="treatment improves operating profit",
        control_definition="retain current allocation",
        treatment_definition="apply approved treatment",
        success_measure="operating profit",
        observation_window=timedelta(days=7),
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        experiment_design_policy_version="design-v1",
        activation_policy_version="activation-v1",
        source_experiment_design_semantics="design-semantics",
        source_experiment_design_contract_version="design-contract-v1",
        source_activation_semantics="externally supplied activation authorization bound to one frozen M11A10 experiment design; preserves deterministic authorization identity and lineage only; no operation specification, no Mission creation, no Worker claim, no Execution creation, no lease acquisition, no scheduling, no dispatch, no platform action, no traffic mutation, no attribution mutation, and no economic inference",
        source_activation_contract_version="m11a11-economic-experiment-activation-authorization-v1",
        successor_operation_spec=EconomicRecommendationExperimentExecutionBindingRow.established_distribution_publish_spec(run_id),
    )


def _distribution_run(session, *, run_id: str | None = None, status: str = "CREATED"):
    run_id = run_id or str(uuid4())
    now = _now()
    discovery_run_id = str(uuid4())
    discovery_candidate_id = str(uuid4())
    content_brief_id = str(uuid4())
    generation_run_id = str(uuid4())
    artifact_id = str(uuid4())
    evaluation_id = str(uuid4())

    session.add(DiscoveryRun(
        id=discovery_run_id,
        input_type="KEYWORD",
        input_value="m11a13 qualification",
        input_data={},
        status="COMPLETED",
        idempotency_key=f"discovery-{discovery_run_id}",
        candidate_count=1,
        verified_count=1,
        selected_count=1,
        created_at=now,
        updated_at=now,
        completed_at=now,
    ))
    session.flush()

    session.add(DiscoveryCandidate(
        id=discovery_candidate_id,
        run_id=discovery_run_id,
        source_adapter="m11a13-qualification",
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
    ))
    session.flush()

    session.add(ContentBrief(
        id=content_brief_id,
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
        idempotency_key=f"brief-{content_brief_id}",
        status="READY",
        created_at=now,
        updated_at=now,
    ))
    session.flush()

    session.add(ContentGenerationRun(
        id=generation_run_id,
        content_brief_id=content_brief_id,
        idempotency_key=f"generation-{generation_run_id}",
        provider="test",
        model="test",
        prompt_version="v1",
        generation_parameters={},
        status="COMPLETED",
        attempt_count=1,
        created_at=now,
        updated_at=now,
    ))
    session.flush()

    session.add(GeneratedContentArtifact(
        id=artifact_id,
        generation_run_id=generation_run_id,
        content_brief_id=content_brief_id,
        content_type="ARTICLE",
        title="proof",
        hook="proof",
        body="proof",
        call_to_action="CHECK_DETAILS",
        affiliate_disclosure="AFFILIATE_DISCLOSURE_REQUIRED",
        claims=[],
        status="GENERATED",
        created_at=now,
        updated_at=now,
    ))
    session.flush()

    session.add(ContentEvaluation(
        id=evaluation_id,
        artifact_id=artifact_id,
        content_brief_id=content_brief_id,
        generation_run_id=generation_run_id,
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
    ))
    session.flush()

    row = DistributionRun(
        id=run_id,
        generated_content_artifact_id=artifact_id,
        content_evaluation_id=evaluation_id,
        platform="test",
        account_reference="account",
        destination="destination",
        status=status,
        publish_generation=0,
        reconciliation_generation=0,
        idempotency_key=f"run-{run_id}",
        prepared_content_body="proof",
        payload_fingerprint="a" * 64,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def _online_worker(session, *, name: str | None = None, capabilities=None):
    worker = Worker(
        name=name or _unique_worker_name(),
        worker_type="content_distribution",
        capabilities=list(capabilities or [CONTENT_DISTRIBUTION_CAPABILITY]),
        status=WorkerStatus.ONLINE.value,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(worker)
    session.flush()
    return worker


def test_m11a13_requires_fresh_guarded_database():
    assert ROLE == "qualification"
    assert URL.drivername.startswith("postgresql")
    assert URL.host == "127.0.0.1"
    assert URL.port == 5432
    assert URL.database == DATABASE
    assert FRESHNESS in {"1", "true", "True", "TRUE"}

    with ENGINE.begin() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        assert current == "c3d4e5f6a7b8"


def test_m11a13_durable_activation_creates_from_created_distribution_run():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="CREATED")
        worker = _online_worker(baseline)
        baseline.commit()

    with Session() as session:
        run = session.query(DistributionRun).filter_by(id=run_id).one()
        assert run.status == "CREATED"
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        result = service.project(request)

        assert result[0].state == OperationActivationState.CREATED
        expected_key = distribution_mission_idempotency_key(run_id)
        mission = session.query(MissionRecord).filter_by(idempotency_key=expected_key).one()
        mission_id = mission.id
        assert mission.status == MissionStatus.RUNNING.value
        assert mission.current_worker_name == worker.name
        execution = session.query(Execution).filter_by(mission_id=mission.id).one()
        assert execution.status == "RUNNING"
        assert execution.workflow_name == CONTENT_DISTRIBUTION_WORKFLOW
        assert json.loads(execution.input_data) == {"distribution_run_id": run_id}
        assert execution.lease_owner is not None
        assert execution.lease_generation == 1
        assert execution.lease_expires_at is not None
        session.rollback()

        fresh = Session()
        try:
            refreshed = fresh.query(DistributionRun).filter_by(id=run_id).one()
            assert refreshed.status == "CREATED"
            assert fresh.query(MissionRecord).filter_by(idempotency_key=expected_key).count() == 0
            assert fresh.query(Execution).filter_by(mission_id=mission_id).count() == 0
        finally:
            fresh.close()


def test_m11a13_idempotent_replay_returns_existing_actionable_state():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="CREATED")
        _online_worker(baseline)
        baseline.commit()

    with Session() as session:
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        first = service.project(request)
        assert first[0].state == OperationActivationState.CREATED
        session.commit()

        second = service.project(request)
        assert second[0].state == OperationActivationState.EXISTING_ACTIONABLE
        expected_key = distribution_mission_idempotency_key(run_id)
        missions = session.query(MissionRecord).filter_by(idempotency_key=expected_key).all()
        assert len(missions) == 1
        mission_id = missions[0].id
        executions = session.query(Execution).filter_by(mission_id=mission_id).all()
        assert len(executions) == 1
        run = session.query(DistributionRun).filter_by(id=run_id).one()
        assert run.status == "CREATED"


def test_m11a13_existing_terminal_operation_is_preserved():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="CREATED")
        _online_worker(baseline)
        baseline.commit()

    with Session() as session:
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        initial = service.project(request)
        assert initial[0].state == OperationActivationState.CREATED
        session.commit()

        mission = session.query(MissionRecord).filter_by(idempotency_key=distribution_mission_idempotency_key(run_id)).one()
        mission.status = MissionStatus.COMPLETED.value
        execution = session.query(Execution).filter_by(mission_id=mission.id).one()
        execution.status = "COMPLETED"
        session.commit()

        replay = service.project(request)
        assert replay[0].state == OperationActivationState.EXISTING_TERMINAL
        assert session.query(MissionRecord).filter_by(idempotency_key=distribution_mission_idempotency_key(run_id)).count() == 1
        assert session.query(Execution).filter_by(mission_id=mission.id).count() == 1
        run = session.query(DistributionRun).filter_by(id=run_id).one()
        assert run.status == "CREATED"


def test_m11a13_non_created_distribution_run_rejected_before_activation():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="SCHEDULED")
        worker = _online_worker(baseline)
        baseline.commit()

    with Session() as session:
        run = session.query(DistributionRun).filter_by(id=run_id).one()
        assert run.status == "SCHEDULED"
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        with pytest.raises(ValueError, match="distribution_run_id must be CREATED"):
            service.project(request)

        expected_key = distribution_mission_idempotency_key(run_id)
        assert session.query(MissionRecord).filter_by(idempotency_key=expected_key).count() == 0
        assert session.query(Execution).filter_by(mission_id=None).count() == 0
        worker_row = session.query(Worker).filter_by(name=worker.name).one()
        assert worker_row.current_mission_id is None
        assert session.query(DistributionRun).filter_by(id=run_id).one().status == "SCHEDULED"


def test_m11a13_no_eligible_worker_leaves_no_committed_side_effects():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="CREATED")
        baseline.commit()

    with Session() as session:
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        with pytest.raises(RuntimeError, match="no eligible worker is available"):
            service.project(request)
        session.rollback()

        fresh = Session()
        try:
            assert fresh.query(DistributionRun).filter_by(id=run_id).one().status == "CREATED"
            assert fresh.query(MissionRecord).filter_by(idempotency_key=distribution_mission_idempotency_key(run_id)).count() == 0
            assert fresh.query(Execution).filter_by(mission_id=None).count() == 0
        finally:
            fresh.close()


def test_m11a13_service_does_not_commit_or_rollback_its_own_transaction():
    run_id = str(uuid4())
    with Session() as baseline:
        _distribution_run(baseline, run_id=run_id, status="CREATED")
        worker = _online_worker(baseline)
        baseline.commit()

    session = Session()
    try:
        row = _binding_row(run_id=run_id)
        request = EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=(row,),
            durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
        )
        service = EconomicRecommendationExperimentDurableActivationService(session)
        result = service.project(request)
        assert result[0].state == OperationActivationState.CREATED
        mission = session.query(MissionRecord).filter_by(idempotency_key=distribution_mission_idempotency_key(run_id)).one()
        mission_id = mission.id
        assert mission.status == MissionStatus.RUNNING.value
        assert session.query(Execution).filter_by(mission_id=mission.id).count() == 1
        worker_row = session.query(Worker).filter_by(name=worker.name).one()
        assert worker_row.current_mission_id == mission.id
        session.rollback()

        fresh = Session()
        try:
            assert fresh.query(DistributionRun).filter_by(id=run_id).one().status == "CREATED"
            assert fresh.query(MissionRecord).filter_by(idempotency_key=distribution_mission_idempotency_key(run_id)).count() == 0
            assert fresh.query(Execution).filter_by(mission_id=mission_id).count() == 0
            worker_after = fresh.query(Worker).filter_by(name=worker.name).one()
            assert worker_after.status == WorkerStatus.ONLINE.value
            assert worker_after.current_mission_id is None
        finally:
            fresh.close()
    finally:
        session.close()
