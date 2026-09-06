"""Immutable observation contracts over frozen M11A12 execution bindings."""

from dataclasses import dataclass
from datetime import datetime

from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS,
    EconomicRecommendationExperimentExecutionBindingRow,
)


ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION = (
    "m11a14-economic-experiment-execution-observation-v1"
)
ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS = (
    "consume exact frozen M11A12 execution-binding rows; deterministically resolve "
    "their M11A13 durable Mission through the established distribution mission "
    "idempotency key; read the canonical latest Execution using the established "
    "ExecutionRepository.get_by_mission_id() descending-ID ordering; read the "
    "referenced persisted DistributionRun; and emit an immutable deterministic "
    "execution/publication observation preserving experiment lineage. DistributionRun "
    "status is authoritative for publication outcome. No mutation, activation, "
    "scheduling, dispatch, publishing, attribution, scoring, winner selection, or "
    "economic inference."
)


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionObservationPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("execution observation policy version must be nonblank")
        return EconomicRecommendationExperimentExecutionObservationPolicy(
            policy_version=self.policy_version.strip(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionObservationRequest:
    execution_binding_rows: tuple
    execution_observation_policy: EconomicRecommendationExperimentExecutionObservationPolicy

    def normalized(self):
        if type(self.execution_binding_rows) is not tuple:
            raise ValueError("execution_binding_rows must be a tuple")
        if type(self.execution_observation_policy) is not EconomicRecommendationExperimentExecutionObservationPolicy:
            raise ValueError("execution observation policy is required")
        rows = []
        for row in self.execution_binding_rows:
            if type(row) is not EconomicRecommendationExperimentExecutionBindingRow:
                raise ValueError("invalid execution binding row")
            rows.append(validate_execution_binding_row(row))
        return EconomicRecommendationExperimentExecutionObservationRequest(
            execution_binding_rows=tuple(rows),
            execution_observation_policy=self.execution_observation_policy.normalized(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentExecutionObservationRow:
    experiment_reference: str
    activation_reference: str
    distribution_run_id: str
    actor_reference: str
    decision_reference: str
    authorized_at: datetime
    mission_id: str
    execution_id: int
    mission_status: str
    execution_status: str
    distribution_run_status: str
    external_post_id: str | None
    external_url: str | None
    platform: str
    account_reference: str
    destination: str
    result_metadata: object | None
    failure_category: str | None
    error_summary: str | None
    distribution_run_completed_at: datetime | None
    execution_completed_at: datetime | None
    mission_completed_at: datetime | None
    terminal_classification: str
    success_failure_classification: str
    execution_observation_policy_version: str
    execution_observation_contract_version: str = (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION
    )
    execution_observation_semantics: str = (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS
    )


def validate_execution_binding_row(row):
    """Accept only the exact frozen M11A12 row and its established operation spec."""
    if type(row) is not EconomicRecommendationExperimentExecutionBindingRow:
        raise ValueError("M11A12 execution-binding row type is invalid")
    if (
        row.execution_binding_semantics
        != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_SEMANTICS
        or row.execution_binding_contract_version
        != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_BINDING_CONTRACT_VERSION
    ):
        raise ValueError("M11A12 execution-binding lineage is invalid")
    expected = EconomicRecommendationExperimentExecutionBindingRow.established_distribution_publish_spec(
        row.distribution_run_id,
    )
    if row.successor_operation_spec != expected:
        raise ValueError("M11A12 successor operation spec is invalid")
    return row
