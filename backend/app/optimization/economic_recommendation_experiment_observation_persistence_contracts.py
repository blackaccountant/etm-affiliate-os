"""Immutable persistence contracts over frozen M11A14 observations."""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.attribution.contracts import canonical_fingerprint
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS,
    EconomicRecommendationExperimentExecutionObservationRow,
)


ECONOMIC_RECOMMENDATION_EXPERIMENT_OBSERVATION_PERSISTENCE_CONTRACT_VERSION = "m11a15-economic-experiment-observation-persistence-v1"
ECONOMIC_RECOMMENDATION_EXPERIMENT_OBSERVATION_PERSISTENCE_SEMANTICS = (
    "persist exact frozen M11A14 execution-observation rows as immutable "
    "fingerprint-addressed snapshots. Exact replay is idempotent; materially "
    "changed later persisted observation facts produce a distinct immutable "
    "observation even when execution_id is unchanged. Preserve experiment, "
    "activation, Mission, Execution, DistributionRun, publication, failure, and "
    "classification lineage without reinterpretation. No attribution calculation, "
    "revenue/profit projection, experiment evaluation, control-vs-treatment "
    "comparison, winner selection, optimization feedback, publishing, "
    "durable-operation activation, or mutation of Mission, Execution, "
    "DistributionRun, or attribution records."
)

SOURCE_FIELDS = (
    "experiment_reference", "activation_reference", "distribution_run_id", "actor_reference",
    "decision_reference", "authorized_at", "mission_id", "execution_id", "mission_status",
    "execution_status", "distribution_run_status", "external_post_id", "external_url",
    "platform", "account_reference", "destination", "result_metadata", "failure_category",
    "error_summary", "distribution_run_completed_at", "execution_completed_at",
    "mission_completed_at", "terminal_classification", "success_failure_classification",
    "execution_observation_policy_version", "execution_observation_contract_version",
    "execution_observation_semantics",
)


class EconomicRecommendationExperimentObservationFingerprintConflict(ValueError):
    """Raised when one fingerprint addresses non-identical immutable snapshots."""


@dataclass(frozen=True)
class EconomicRecommendationExperimentObservationPersistencePolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("observation persistence policy version must be nonblank")
        return EconomicRecommendationExperimentObservationPersistencePolicy(self.policy_version.strip())


def _datetime_value(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def observation_snapshot(source):
    """Return the complete, stable JSON-ready M11A14 source snapshot."""
    validate_execution_observation_row(source)
    values = {}
    for field in SOURCE_FIELDS:
        value = getattr(source, field)
        if field in {"authorized_at", "distribution_run_completed_at", "execution_completed_at", "mission_completed_at"}:
            values[field] = None if value is None else _datetime_value(value, field)
        else:
            values[field] = value
    return values


def observation_fingerprint(source):
    return canonical_fingerprint(
        ECONOMIC_RECOMMENDATION_EXPERIMENT_OBSERVATION_PERSISTENCE_CONTRACT_VERSION,
        observation_snapshot(source),
    )


def validate_execution_observation_row(row):
    if type(row) is not EconomicRecommendationExperimentExecutionObservationRow:
        raise ValueError("M11A14 execution-observation row type is invalid")
    if row.execution_observation_contract_version != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_CONTRACT_VERSION:
        raise ValueError("M11A14 execution-observation contract version is invalid")
    if row.execution_observation_semantics != ECONOMIC_RECOMMENDATION_EXPERIMENT_EXECUTION_OBSERVATION_SEMANTICS:
        raise ValueError("M11A14 execution-observation semantics is invalid")
    required_text = ("experiment_reference", "activation_reference", "distribution_run_id", "actor_reference", "decision_reference", "mission_id", "mission_status", "execution_status", "distribution_run_status", "platform", "account_reference", "destination", "terminal_classification", "success_failure_classification", "execution_observation_policy_version")
    for field in required_text:
        if type(getattr(row, field)) is not str or not getattr(row, field).strip():
            raise ValueError(f"M11A14 {field} is invalid")
    if type(row.execution_id) is not int or isinstance(row.execution_id, bool) or row.execution_id < 1:
        raise ValueError("M11A14 execution_id is invalid")
    _datetime_value(row.authorized_at, "authorized_at")
    for field in ("distribution_run_completed_at", "execution_completed_at", "mission_completed_at"):
        value = getattr(row, field)
        if value is not None:
            _datetime_value(value, field)
    return row


@dataclass(frozen=True)
class EconomicRecommendationExperimentObservationPersistenceRequest:
    execution_observation_rows: tuple
    observation_persistence_policy: EconomicRecommendationExperimentObservationPersistencePolicy

    def normalized(self):
        if type(self.execution_observation_rows) is not tuple:
            raise ValueError("execution_observation_rows must be a tuple")
        if type(self.observation_persistence_policy) is not EconomicRecommendationExperimentObservationPersistencePolicy:
            raise ValueError("observation persistence policy is required")
        return EconomicRecommendationExperimentObservationPersistenceRequest(
            tuple(validate_execution_observation_row(row) for row in self.execution_observation_rows),
            self.observation_persistence_policy.normalized(),
        )
