"""Read-only execution-binding contracts over frozen M11A11 activation authorization."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_MISSION_NAME,
    CONTENT_DISTRIBUTION_WORKFLOW,
    DistributionWorkflowPayload,
    distribution_mission_idempotency_key,
)
from app.services.durable_operation_activation_service import SuccessorOperationSpec

ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION = (
    "m11a12-economic-experiment-execution-binding-v1"
)

ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS = (
    "bind one frozen M11A11 activation authorization to one persisted "
    "DistributionRun and deterministically emit the established "
    "distribution_publish SuccessorOperationSpec; no Mission creation, "
    "no Execution creation, no Worker claim, no lease acquisition, no "
    "scheduling, no dispatch, no publishing, no platform action, no "
    "DistributionRun mutation, and no economic inference"
)


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionBindingPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("execution binding policy version must be nonblank")
        return EconomicRecommendationExperimentExecutionBindingPolicy(
            policy_version=self.policy_version.strip(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionBinding:
    activation_reference: str
    distribution_run_id: str

    def normalized(self):
        if type(self.activation_reference) is not str or not self.activation_reference.strip():
            raise ValueError("activation_reference must be nonblank")
        if type(self.distribution_run_id) is not str or not self.distribution_run_id.strip():
            raise ValueError("distribution_run_id must be nonblank")
        return EconomicRecommendationExperimentExecutionBinding(
            activation_reference=self.activation_reference.strip(),
            distribution_run_id=self.distribution_run_id.strip(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionBindingRequest:
    experiment_activation_request: object
    execution_bindings: tuple
    execution_binding_policy: EconomicRecommendationExperimentExecutionBindingPolicy

    def normalized(self):
        if type(self.execution_bindings) is not tuple:
            raise ValueError("execution_bindings must be a tuple")
        if type(self.execution_binding_policy) is not EconomicRecommendationExperimentExecutionBindingPolicy:
            raise ValueError("execution binding policy is required")

        normalized_bindings = []
        for item in self.execution_bindings:
            if type(item) is not EconomicRecommendationExperimentExecutionBinding:
                raise ValueError("invalid execution binding")
            normalized_bindings.append(item.normalized())

        return EconomicRecommendationExperimentExecutionBindingRequest(
            experiment_activation_request=self.experiment_activation_request,
            execution_bindings=tuple(normalized_bindings),
            execution_binding_policy=self.execution_binding_policy.normalized(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionBindingRow:
    experiment_reference: str
    activation_reference: str
    distribution_run_id: str

    actor_reference: str
    decision_reference: str
    authorized_at: datetime

    design_reference: str
    designed_at: datetime

    hypothesis: str
    control_definition: str
    treatment_definition: str
    success_measure: str
    observation_window: timedelta

    recommendation_policy_version: str
    approval_policy_version: str
    experiment_design_policy_version: str
    activation_policy_version: str

    source_experiment_design_semantics: str
    source_experiment_design_contract_version: str
    source_activation_semantics: str
    source_activation_contract_version: str

    execution_binding_semantics: str = ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS
    execution_binding_contract_version: str = ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION
    successor_operation_spec: SuccessorOperationSpec | None = None

    def normalized(self):
        if type(self.successor_operation_spec) is not SuccessorOperationSpec:
            raise ValueError("successor operation spec is required")
        return self

    @staticmethod
    def established_distribution_publish_spec(distribution_run_id: str):
        return SuccessorOperationSpec(
            name=CONTENT_DISTRIBUTION_MISSION_NAME,
            objective="publish approved content to configured destination",
            workflow=CONTENT_DISTRIBUTION_WORKFLOW,
            required_capability=CONTENT_DISTRIBUTION_CAPABILITY,
            idempotency_key=distribution_mission_idempotency_key(distribution_run_id),
            payload=DistributionWorkflowPayload(distribution_run_id).to_dict(),
        )
