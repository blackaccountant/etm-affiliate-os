"""Focused contracts for M11A14 economic experiment execution observation."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    EconomicRecommendationExperimentExecutionBindingRow,
)
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS,
    EconomicRecommendationExperimentExecutionObservationPolicy,
    EconomicRecommendationExperimentExecutionObservationRequest,
    validate_execution_binding_row,
)
from app.services.economic_recommendation_experiment_execution_observation_service import (
    EconomicRecommendationExperimentExecutionObservationService,
)

NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)


def _binding_row(run_id="run-1"):
    return EconomicRecommendationExperimentExecutionBindingRow(
        experiment_reference="experiment-1", activation_reference="activation-1",
        distribution_run_id=run_id, actor_reference="actor-1", decision_reference="decision-1",
        authorized_at=NOW, design_reference="design-1", designed_at=NOW,
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


def _run(status="COMPLETED"):
    return SimpleNamespace(
        id="run-1", status=status, external_post_id="post-1", external_url="https://example.test/post-1",
        platform="test", account_reference="account-1", destination="destination-1",
        result_metadata={"provider": "test"}, failure_category="failure", error_summary="error",
        completed_at=NOW + timedelta(hours=1),
    )


class _Runs:
    def __init__(self, run): self.run = run
    def get_by_id(self, run_id): return self.run if self.run and self.run.id == run_id else None


class _Missions:
    def __init__(self, mission): self.mission = mission
    def get_by_idempotency_key(self, key): return self.mission if self.mission and self.mission.idempotency_key == key else None


class _Executions:
    def __init__(self, executions): self.executions = executions
    def get_by_mission_id(self, mission_id): return self.executions


class _Db:
    def __init__(self): self.committed = self.rolled_back = False
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True


def _service(status="COMPLETED", executions=None, mission=None):
    mission = mission or SimpleNamespace(id="mission-1", idempotency_key="distribution:run-1", status="COMPLETED", completed_at=NOW)
    executions = executions if executions is not None else [SimpleNamespace(id=7, mission_id="mission-1", status="COMPLETED", completed_at=NOW)]
    db = _Db()
    return db, EconomicRecommendationExperimentExecutionObservationService(
        db, distribution_run_repository=_Runs(_run(status)), mission_repository=_Missions(mission),
        execution_repository=_Executions(executions),
    )


def _request(rows=None):
    return EconomicRecommendationExperimentExecutionObservationRequest(
        execution_binding_rows=(_binding_row(),) if rows is None else rows,
        execution_observation_policy=EconomicRecommendationExperimentExecutionObservationPolicy(" observation-v1 "),
    )


def test_contract_metadata_and_policy_are_frozen():
    assert ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION == "m11a14-economic-experiment-execution-observation-v1"
    assert "DistributionRun status is authoritative" in ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS
    assert EconomicRecommendationExperimentExecutionObservationPolicy(" policy ").normalized().policy_version == "policy"


@pytest.mark.parametrize("value", ["", " ", None, 1])
def test_policy_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="execution observation policy version must be nonblank"):
        EconomicRecommendationExperimentExecutionObservationPolicy(value).normalized()


def test_request_requires_tuple_and_exact_m11a12_rows():
    with pytest.raises(ValueError, match="execution_binding_rows must be a tuple"):
        _request(rows=[]).normalized()
    with pytest.raises(ValueError, match="invalid execution binding row"):
        _request(rows=(SimpleNamespace(**vars(_binding_row())),)).normalized()
    with pytest.raises(ValueError, match="M11A12 execution-binding row type is invalid"):
        validate_execution_binding_row(SimpleNamespace(**vars(_binding_row())))


@pytest.mark.parametrize("field, value, message", [
    ("execution_binding_semantics", "wrong", "M11A12 execution-binding lineage is invalid"),
    ("execution_binding_contract_version", "wrong", "M11A12 execution-binding lineage is invalid"),
    ("successor_operation_spec", object(), "M11A12 successor operation spec is invalid"),
])
def test_frozen_m11a12_validation_rejects_invalid_lineage(field, value, message):
    row = _binding_row()
    row = EconomicRecommendationExperimentExecutionBindingRow(**{**vars(row), field: value})
    with pytest.raises(ValueError, match=message):
        validate_execution_binding_row(row)


@pytest.mark.parametrize("status, terminal, outcome", [
    ("COMPLETED", "TERMINAL", "SUCCESS"), ("FAILED", "TERMINAL", "FAILURE"),
    ("CANCELLED", "TERMINAL", "FAILURE"), ("RECONCILIATION_REQUIRED", "NON_TERMINAL", "UNRESOLVED"),
    ("RUNNING", "NON_TERMINAL", "UNRESOLVED"),
])
def test_observation_preserves_facts_and_distribution_status_is_authoritative(status, terminal, outcome):
    _, service = _service(status)
    observation = service.project(_request())[0]
    assert observation.experiment_reference == "experiment-1"
    assert observation.activation_reference == "activation-1"
    assert observation.distribution_run_id == "run-1"
    assert observation.actor_reference == "actor-1"
    assert observation.decision_reference == "decision-1"
    assert observation.authorized_at == NOW
    assert observation.mission_id == "mission-1" and observation.execution_id == 7
    assert observation.external_post_id == "post-1"
    assert observation.external_url == "https://example.test/post-1"
    assert observation.platform == "test"
    assert observation.account_reference == "account-1"
    assert observation.destination == "destination-1"
    assert observation.result_metadata == {"provider": "test"}
    assert observation.failure_category == "failure"
    assert observation.error_summary == "error"
    assert observation.distribution_run_completed_at == NOW + timedelta(hours=1)
    assert observation.execution_completed_at == NOW
    assert observation.mission_completed_at == NOW
    assert observation.execution_observation_policy_version == "observation-v1"
    assert (observation.terminal_classification, observation.success_failure_classification) == (terminal, outcome)


def test_missing_durable_lineage_is_rejected():
    db, service = _service()
    service._distribution_runs = _Runs(None)
    with pytest.raises(ValueError, match="distribution_run_id does not exist"): service.project(_request())
    db, service = _service(); service._missions = _Missions(None)
    with pytest.raises(ValueError, match="distribution mission does not exist"): service.project(_request())
    db, service = _service(); service._executions = _Executions([])
    with pytest.raises(ValueError, match="distribution mission execution does not exist"): service.project(_request())


def test_canonical_execution_is_first_descending_repository_result_and_no_transaction_is_owned():
    db, service = _service(executions=[
        SimpleNamespace(id=99, mission_id="mission-1", status="FAILED", completed_at=NOW),
        SimpleNamespace(id=3, mission_id="mission-1", status="COMPLETED", completed_at=NOW),
    ])
    observation = service.project(_request())[0]
    assert observation.execution_id == 99
    assert observation.execution_status == "FAILED"
    assert observation.success_failure_classification == "SUCCESS"
    assert db.committed is False and db.rolled_back is False
