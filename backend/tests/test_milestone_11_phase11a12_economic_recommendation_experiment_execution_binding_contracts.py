"""Focused contracts for M11A12 economic experiment execution binding."""

from datetime import datetime, timedelta, timezone

import pytest

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_MISSION_NAME,
    CONTENT_DISTRIBUTION_WORKFLOW,
    distribution_mission_idempotency_key,
)
from app.optimization.economic_recommendation_experiment_activation_contracts import (
    EconomicRecommendationExperimentActivationDecision,
    EconomicRecommendationExperimentActivationPolicy,
    EconomicRecommendationExperimentActivationRow,
)
from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS,
    EconomicRecommendationExperimentExecutionBinding,
    EconomicRecommendationExperimentExecutionBindingPolicy,
    EconomicRecommendationExperimentExecutionBindingRequest,
)
from app.services.economic_recommendation_experiment_execution_binding_service import (
    EconomicRecommendationExperimentExecutionBindingService,
)

NOW = datetime(2026, 9, 6, 5, 0, tzinfo=timezone.utc)


def activation_row(*, activation_reference="activation-1", experiment_reference="experiment-1"):
    return EconomicRecommendationExperimentActivationRow(
        experiment_reference=experiment_reference,
        activation_reference=activation_reference,
        hypothesis="treatment improves operating profit",
        control_definition="retain current allocation",
        treatment_definition="apply approved treatment",
        success_measure="operating profit",
        observation_window=timedelta(days=7),
        actor_reference="activation-actor",
        decision_reference="activation-decision-1",
        authorized_at=NOW + timedelta(minutes=1),
        design_reference="design-1",
        designed_at=NOW,
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        experiment_design_policy_version="design-v1",
        activation_policy_version="activation-v1",
        source_experiment_design_semantics="design-semantics",
        source_experiment_design_contract_version="design-contract-v1",
        activation_semantics="externally supplied activation authorization bound to one frozen M11A10 experiment design; preserves deterministic authorization identity and lineage only; no operation specification, no Mission creation, no Worker claim, no Execution creation, no lease acquisition, no scheduling, no dispatch, no platform action, no traffic mutation, no attribution mutation, and no economic inference",
        activation_contract_version="m11a11-economic-experiment-activation-authorization-v1",
    )


class StubActivationService:
    def __init__(self, rows):
        self.rows = rows

    def project(self, request):
        return tuple(self.rows)


class StubRunRepository:
    def __init__(self, present):
        self.present = set(present)

    def get_by_id(self, run_id):
        return {"id": run_id} if run_id in self.present else None


def build_request(bindings, *, activation_rows):
    return EconomicRecommendationExperimentExecutionBindingRequest(
        experiment_activation_request=object(),
        execution_bindings=tuple(bindings),
        execution_binding_policy=EconomicRecommendationExperimentExecutionBindingPolicy(
            "execution-binding-v1"
        ),
    )


def test_execution_binding_contract_metadata_is_frozen():
    semantics = ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS
    assert ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION == "m11a12-economic-experiment-execution-binding-v1"
    assert "bind one frozen M11A11 activation authorization" in semantics
    assert "DistributionRun" in semantics
    assert "SuccessorOperationSpec" in semantics
    assert "no Mission creation" in semantics
    assert "no Execution creation" in semantics
    assert "no Worker claim" in semantics
    assert "no lease acquisition" in semantics
    assert "no scheduling" in semantics
    assert "no dispatch" in semantics
    assert "no publishing" in semantics
    assert "no platform action" in semantics
    assert "no DistributionRun mutation" in semantics


def test_execution_binding_policy_normalizes_version():
    policy = EconomicRecommendationExperimentExecutionBindingPolicy(" execution-binding-v1 ").normalized()
    assert policy.policy_version == "execution-binding-v1"


@pytest.mark.parametrize("value", ["", "   ", None, 1])
def test_execution_binding_policy_rejects_invalid_version(value):
    with pytest.raises(ValueError, match="policy version must be nonblank"):
        EconomicRecommendationExperimentExecutionBindingPolicy(value).normalized()


def test_execution_binding_normalizes_fields():
    binding = EconomicRecommendationExperimentExecutionBinding(
        activation_reference=" activation-1 ",
        distribution_run_id=" run-1 ",
    ).normalized()
    assert binding.activation_reference == "activation-1"
    assert binding.distribution_run_id == "run-1"


@pytest.mark.parametrize(("field", "value"), [("activation_reference", ""), ("distribution_run_id", None)])
def test_execution_binding_rejects_invalid_fields(field, value):
    data = {"activation_reference": "activation-1", "distribution_run_id": "run-1"}
    data[field] = value
    with pytest.raises(ValueError):
        EconomicRecommendationExperimentExecutionBinding(**data).normalized()


def test_service_binds_known_activation_to_existing_distribution_run_and_emits_spec():
    rows = [activation_row()]
    request = build_request(
        [EconomicRecommendationExperimentExecutionBinding("activation-1", "run-1")],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository(["run-1"]),
    )
    result = service.project(request)
    assert len(result) == 1
    item = result[0]
    assert item.activation_reference == "activation-1"
    assert item.distribution_run_id == "run-1"
    assert item.successor_operation_spec.name == CONTENT_DISTRIBUTION_MISSION_NAME
    assert item.successor_operation_spec.objective == "publish approved content to configured destination"
    assert item.successor_operation_spec.workflow == CONTENT_DISTRIBUTION_WORKFLOW
    assert item.successor_operation_spec.required_capability == CONTENT_DISTRIBUTION_CAPABILITY
    assert item.successor_operation_spec.idempotency_key == distribution_mission_idempotency_key("run-1")
    assert item.successor_operation_spec.payload == {"distribution_run_id": "run-1"}


def test_service_rejects_unknown_activation_reference():
    rows = [activation_row()]
    request = build_request(
        [EconomicRecommendationExperimentExecutionBinding("activation-2", "run-1")],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository(["run-1"]),
    )
    with pytest.raises(ValueError, match="unknown activation_reference"):
        service.project(request)


def test_service_rejects_duplicate_activation_reference():
    rows = [activation_row(), activation_row(activation_reference="activation-2")]
    request = build_request(
        [
            EconomicRecommendationExperimentExecutionBinding("activation-1", "run-1"),
            EconomicRecommendationExperimentExecutionBinding("activation-1", "run-2"),
        ],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository(["run-1", "run-2"]),
    )
    with pytest.raises(ValueError, match="duplicate activation_reference"):
        service.project(request)


def test_service_rejects_duplicate_distribution_run_id():
    rows = [activation_row(), activation_row(activation_reference="activation-2")]
    request = build_request(
        [
            EconomicRecommendationExperimentExecutionBinding("activation-1", "run-1"),
            EconomicRecommendationExperimentExecutionBinding("activation-2", "run-1"),
        ],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository(["run-1"]),
    )
    with pytest.raises(ValueError, match="duplicate distribution_run_id"):
        service.project(request)


def test_service_rejects_missing_distribution_run():
    rows = [activation_row()]
    request = build_request(
        [EconomicRecommendationExperimentExecutionBinding("activation-1", "missing-run")],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository([]),
    )
    with pytest.raises(ValueError, match="distribution_run_id does not exist"):
        service.project(request)


def test_service_preserves_activation_order_and_allows_subset_binding():
    rows = [activation_row(activation_reference="activation-1"), activation_row(activation_reference="activation-2")]
    request = build_request(
        [EconomicRecommendationExperimentExecutionBinding("activation-2", "run-2")],
        activation_rows=rows,
    )
    service = EconomicRecommendationExperimentExecutionBindingService(
        object(),
        activation_service=StubActivationService(rows),
        distribution_run_repository=StubRunRepository(["run-2"]),
    )
    result = service.project(request)
    assert [item.activation_reference for item in result] == ["activation-2"]
