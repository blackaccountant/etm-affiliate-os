"""Focused contracts for M11A13 durable operation activation over M11A12 binding rows."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    EconomicRecommendationExperimentExecutionBindingRow,
)
from app.optimization.economic_recommendation_experiment_durable_activation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS,
    EconomicRecommendationExperimentDurableActivationPolicy,
    EconomicRecommendationExperimentDurableActivationRequest,
    validate_execution_binding_row,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.durable_operation_activation_service import (
    OperationActivationState,
)
from app.services.economic_recommendation_experiment_durable_activation_service import (
    EconomicRecommendationExperimentDurableActivationService,
)

NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)


def _binding_row(*, run_id="run-1", activation_reference="activation-1"):
    return EconomicRecommendationExperimentExecutionBindingRow(
        experiment_reference="experiment-1",
        activation_reference=activation_reference,
        distribution_run_id=run_id,
        actor_reference="activation-actor",
        decision_reference="activation-decision-1",
        authorized_at=NOW + timedelta(minutes=1),
        design_reference="design-1",
        designed_at=NOW,
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


class StubActivationService:
    def __init__(self, states):
        self.states = list(states)

    def activate(self, spec):
        state = self.states.pop(0)
        return SimpleNamespace(spec=spec, state=state, mission_id="mission-1")


class StubRunRepository:
    def __init__(self, status_by_id):
        self.status_by_id = status_by_id

    def get_by_id(self, run_id):
        status = self.status_by_id.get(run_id)
        if status is None:
            return None
        return SimpleNamespace(id=run_id, status=status)


class TrackingDb:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_contract_metadata_is_frozen():
    assert ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_CONTRACT_VERSION == "m11a13-economic-experiment-durable-operation-activation-v1"
    assert "M11A12 execution-binding rows" in ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS
    assert "DurableOperationActivationService.activate" in ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS
    assert "CREATED" in ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS
    assert "EXISTING_ACTIONABLE" in ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS
    assert "EXISTING_TERMINAL" in ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS


def test_policy_normalizes_version():
    policy = EconomicRecommendationExperimentDurableActivationPolicy(" durable-v1 ").normalized()
    assert policy.policy_version == "durable-v1"


@pytest.mark.parametrize("value", ["", "   ", None, 1])
def test_policy_rejects_invalid_version(value):
    with pytest.raises(ValueError, match="durable activation policy version must be nonblank"):
        EconomicRecommendationExperimentDurableActivationPolicy(value).normalized()


def test_validation_rejects_exact_m11a12_row_type():
    row = SimpleNamespace(**vars(_binding_row()))
    with pytest.raises(ValueError, match="M11A12 execution-binding row type is invalid"):
        validate_execution_binding_row(row)


def test_validation_rejects_bad_semantics():
    row = _binding_row()
    row = EconomicRecommendationExperimentExecutionBindingRow(**{**vars(row), "execution_binding_semantics": "wrong"})
    with pytest.raises(ValueError, match="M11A12 execution-binding lineage is invalid"):
        validate_execution_binding_row(row)


def test_validation_rejects_bad_contract_version():
    row = _binding_row()
    row = EconomicRecommendationExperimentExecutionBindingRow(**{**vars(row), "execution_binding_contract_version": "wrong"})
    with pytest.raises(ValueError, match="M11A12 execution-binding lineage is invalid"):
        validate_execution_binding_row(row)


def test_validation_rejects_malformed_successor_operation_spec():
    row = _binding_row()
    row = EconomicRecommendationExperimentExecutionBindingRow(**{**vars(row), "successor_operation_spec": object()})
    with pytest.raises(ValueError, match="M11A12 successor operation spec is invalid"):
        validate_execution_binding_row(row)


def test_default_distribution_run_repository_wiring():
    service = EconomicRecommendationExperimentDurableActivationService(
        object(),
        activation_service=StubActivationService([OperationActivationState.CREATED]),
    )
    assert isinstance(service._distribution_runs, DistributionRunRepository)


def test_service_rejects_missing_distribution_run():
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(_binding_row(),),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    service = EconomicRecommendationExperimentDurableActivationService(
        object(),
        activation_service=StubActivationService([OperationActivationState.CREATED]),
        distribution_run_repository=StubRunRepository({}),
    )
    with pytest.raises(ValueError, match="distribution_run_id does not exist"):
        service.project(request)


def test_service_rejects_non_created_distribution_run():
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(_binding_row(),),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    service = EconomicRecommendationExperimentDurableActivationService(
        object(),
        activation_service=StubActivationService([OperationActivationState.CREATED]),
        distribution_run_repository=StubRunRepository({"run-1": "SCHEDULED"}),
    )

    with pytest.raises(ValueError, match="distribution_run_id must be CREATED"):
        service.project(request)


def test_service_activates_created_distribution_run_and_preserves_created_state():
    row = _binding_row()
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(row,),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    service = EconomicRecommendationExperimentDurableActivationService(
        TrackingDb(),
        activation_service=StubActivationService([OperationActivationState.CREATED]),
        distribution_run_repository=StubRunRepository({"run-1": "CREATED"}),
    )

    result = service.project(request)
    assert len(result) == 1
    assert result[0].state == OperationActivationState.CREATED
    assert result[0].spec.idempotency_key == "distribution:run-1"
    assert service.db.committed is False
    assert service.db.rolled_back is False


def test_service_preserves_existing_actionable_and_terminal_states():
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(_binding_row(run_id="run-1"), _binding_row(run_id="run-2", activation_reference="activation-2")),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    service = EconomicRecommendationExperimentDurableActivationService(
        TrackingDb(),
        activation_service=StubActivationService([
            OperationActivationState.EXISTING_ACTIONABLE,
            OperationActivationState.EXISTING_TERMINAL,
        ]),
        distribution_run_repository=StubRunRepository({"run-1": "CREATED", "run-2": "CREATED"}),
    )

    result = service.project(request)
    assert [item.state for item in result] == [
        OperationActivationState.EXISTING_ACTIONABLE,
        OperationActivationState.EXISTING_TERMINAL,
    ]


def test_empty_tuple_returns_deterministic_empty_result():
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    service = EconomicRecommendationExperimentDurableActivationService(
        TrackingDb(),
        activation_service=StubActivationService([]),
        distribution_run_repository=StubRunRepository({}),
    )
    assert service.project(request) == ()


def test_service_does_not_mutate_distribution_run_or_own_transaction():
    run = SimpleNamespace(id="run-1", status="CREATED")
    request = EconomicRecommendationExperimentDurableActivationRequest(
        execution_binding_rows=(_binding_row(),),
        durable_activation_policy=EconomicRecommendationExperimentDurableActivationPolicy("durable-v1"),
    )
    db = TrackingDb()
    service = EconomicRecommendationExperimentDurableActivationService(
        db,
        activation_service=StubActivationService([OperationActivationState.CREATED]),
        distribution_run_repository=SimpleNamespace(get_by_id=lambda run_id: run if run_id == "run-1" else None),
    )

    service.project(request)
    assert run.status == "CREATED"
    assert db.committed is False
    assert db.rolled_back is False
