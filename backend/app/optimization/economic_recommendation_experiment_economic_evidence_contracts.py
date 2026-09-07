"""Read-only economic-evidence contracts over frozen M11A15 observations."""

from dataclasses import dataclass
from decimal import Decimal

from app.models.economic_recommendation_experiment_observation import (
    EconomicRecommendationExperimentObservation,
)


ECONOMIC_RECOMMENDATION_EXPERIMENT_ECONOMIC_EVIDENCE_CONTRACT_VERSION = (
    "m11a16-economic-experiment-economic-evidence-v1"
)
ECONOMIC_RECOMMENDATION_EXPERIMENT_ECONOMIC_EVIDENCE_SEMANTICS = (
    "resolve existing M10A8 net realized revenue evidence to exact frozen M11A15 "
    "durable experiment-observation lineage using distribution_run_id. Emit "
    "deterministic immutable in-memory experiment economic-evidence rows preserving "
    "experiment, activation, Mission, Execution, DistributionRun, source economic "
    "dimensions, currency, source semantics, and observation classifications without "
    "reinterpretation. Missing economic evidence is represented explicitly as "
    "NO_EVIDENCE and Decimal(0) remains resolved evidence. No experiment "
    "success/outcome evaluation, control-vs-treatment comparison, winner selection, "
    "recommendation mutation, optimization feedback, attribution creation/write/"
    "recalculation, persistence, transaction commit/rollback ownership, FX conversion, "
    "cross-currency aggregation, publishing, scheduling, dispatch, durable-operation "
    "activation, or mutation of M11A10-M11A15, Mission, Execution, DistributionRun, "
    "or attribution records."
)

NET_REALIZED_REVENUE_PROJECTION_TYPE = "net_realized_revenue"
RESOLVED = "RESOLVED"
NO_EVIDENCE = "NO_EVIDENCE"
EVIDENCE_RESOLUTION_CLASSIFICATIONS = frozenset({RESOLVED, NO_EVIDENCE})


@dataclass(frozen=True)
class EconomicRecommendationExperimentEconomicEvidencePolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("economic evidence policy version must be nonblank")
        return EconomicRecommendationExperimentEconomicEvidencePolicy(self.policy_version.strip())


def validate_observation(observation):
    if type(observation) is not EconomicRecommendationExperimentObservation:
        raise ValueError("M11A15 observation type is invalid")
    required_text = (
        "observation_fingerprint", "experiment_reference", "activation_reference",
        "distribution_run_id", "mission_id", "mission_status", "execution_status",
        "distribution_run_status", "terminal_classification",
        "success_failure_classification",
    )
    for field in required_text:
        value = getattr(observation, field)
        if type(value) is not str or not value.strip():
            raise ValueError(f"M11A15 {field} is invalid")
    if type(observation.execution_id) is not int or isinstance(observation.execution_id, bool) or observation.execution_id < 1:
        raise ValueError("M11A15 execution_id is invalid")
    return observation


@dataclass(frozen=True)
class EconomicRecommendationExperimentEconomicEvidenceRequest:
    observations: tuple
    economic_evidence_policy: EconomicRecommendationExperimentEconomicEvidencePolicy

    def normalized(self):
        if type(self.observations) is not tuple:
            raise ValueError("observations must be a tuple")
        if type(self.economic_evidence_policy) is not EconomicRecommendationExperimentEconomicEvidencePolicy:
            raise ValueError("economic evidence policy is required")
        return EconomicRecommendationExperimentEconomicEvidenceRequest(
            observations=tuple(validate_observation(item) for item in self.observations),
            economic_evidence_policy=self.economic_evidence_policy.normalized(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentEconomicEvidenceRow:
    observation_fingerprint: str
    experiment_reference: str
    activation_reference: str
    distribution_run_id: str
    mission_id: str
    execution_id: int
    mission_status: str
    execution_status: str
    distribution_run_status: str
    terminal_classification: str
    success_failure_classification: str
    source_projection_type: str
    source_projection_semantics: str
    source_dimensions: tuple[tuple[str, str | int | None], ...]
    net_realized_commission: Decimal | None
    currency: str | None
    evidence_resolution_classification: str
