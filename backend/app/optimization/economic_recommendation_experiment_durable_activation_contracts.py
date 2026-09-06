"""Durable operation activation contracts over frozen M11A12 execution-binding rows."""

from dataclasses import dataclass

from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS,
    EconomicRecommendationExperimentExecutionBindingRow,
)

ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_CONTRACT_VERSION = (
    "m11a13-economic-experiment-durable-operation-activation-v1"
)

ECONOMIC_RECOMMENDATION_EXPERIMENT_DURABLE_ACTIVATION_SEMANTICS = (
    "consume frozen M11A12 execution-binding rows, validate the exact M11A12 "
    "lineage and the established distribution_publish SuccessorOperationSpec, "
    "require the referenced DistributionRun to exist and remain in CREATED status, "
    "then delegate to DurableOperationActivationService.activate(spec) while "
    "preserving CREATED, EXISTING_ACTIONABLE, and EXISTING_TERMINAL states; "
    "no DistributionRun mutation, scheduling, dispatch, publishing, attribution "
    "mutation, economic inference, commit, rollback, session close, or new migration"
)


@dataclass(frozen=True)
class EconomicRecommendationExperimentDurableActivationPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("durable activation policy version must be nonblank")
        return EconomicRecommendationExperimentDurableActivationPolicy(
            policy_version=self.policy_version.strip(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentDurableActivationRequest:
    execution_binding_rows: tuple
    durable_activation_policy: EconomicRecommendationExperimentDurableActivationPolicy

    def normalized(self):
        if type(self.execution_binding_rows) is not tuple:
            raise ValueError("execution_binding_rows must be a tuple")
        if type(self.durable_activation_policy) is not EconomicRecommendationExperimentDurableActivationPolicy:
            raise ValueError("durable activation policy is required")

        normalized_rows = []
        for item in self.execution_binding_rows:
            if type(item) is not EconomicRecommendationExperimentExecutionBindingRow:
                raise ValueError("invalid execution binding row")
            normalized_rows.append(item)

        return EconomicRecommendationExperimentDurableActivationRequest(
            execution_binding_rows=tuple(normalized_rows),
            durable_activation_policy=self.durable_activation_policy.normalized(),
        )


def validate_execution_binding_row(row):
    if type(row) is not EconomicRecommendationExperimentExecutionBindingRow:
        raise ValueError("M11A12 execution-binding row type is invalid")
    if (
        row.execution_binding_semantics != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS
        or row.execution_binding_contract_version != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION
    ):
        raise ValueError("M11A12 execution-binding lineage is invalid")

    expected_spec = EconomicRecommendationExperimentExecutionBindingRow.established_distribution_publish_spec(
        row.distribution_run_id,
    )
    if row.successor_operation_spec != expected_spec:
        raise ValueError("M11A12 successor operation spec is invalid")
    return row
