"""Read-only experiment-design contracts bound to frozen M11A9 approval."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.optimization.economic_recommendation_approval_contracts import (
    EconomicRecommendationApprovalRequest,
)


ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION = (
    "m11a10-approved-economic-experiment-design-v1"
)
ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS = (
    "read-only externally supplied experiment design bound to frozen M11A9 approval; "
    "no allocation, scheduling, execution, platform action, traffic mutation, "
    "or economic inference"
)


@dataclass(frozen=True)
class EconomicRecommendationExperimentDesignPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("experiment design policy version must be nonblank")
        return self


@dataclass(frozen=True)
class EconomicRecommendationExperimentDesignInput:
    experiment_reference: str
    approved_dimensions: tuple
    hypothesis: str
    control_definition: str
    treatment_definition: str
    success_measure: str
    observation_window: timedelta
    design_reference: str
    designed_at: datetime

    def normalized(self):
        text_values = (
            self.experiment_reference,
            self.hypothesis,
            self.control_definition,
            self.treatment_definition,
            self.success_measure,
            self.design_reference,
        )
        if any(type(value) is not str or not value.strip() for value in text_values):
            raise ValueError("experiment design text fields must be nonblank")
        if type(self.approved_dimensions) is not tuple:
            raise ValueError("approved_dimensions must be a tuple")
        if (
            type(self.observation_window) is not timedelta
            or self.observation_window <= timedelta(0)
        ):
            raise ValueError("observation_window must be a positive timedelta")
        if (
            type(self.designed_at) is not datetime
            or self.designed_at.tzinfo is None
            or self.designed_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("designed_at must be timezone-aware UTC")
        return self


@dataclass(frozen=True)
class EconomicRecommendationExperimentDesignRequest:
    approval_request: EconomicRecommendationApprovalRequest
    experiment_design_inputs: tuple
    experiment_design_policy: EconomicRecommendationExperimentDesignPolicy

    def normalized(self):
        if type(self.approval_request) is not EconomicRecommendationApprovalRequest:
            raise ValueError("approval request is required")
        if type(self.experiment_design_inputs) is not tuple:
            raise ValueError("experiment_design_inputs must be a tuple")
        if type(self.experiment_design_policy) is not EconomicRecommendationExperimentDesignPolicy:
            raise ValueError("experiment design policy is required")

        normalized_inputs = []
        for item in self.experiment_design_inputs:
            if type(item) is not EconomicRecommendationExperimentDesignInput:
                raise ValueError("invalid experiment design input")
            normalized_inputs.append(item.normalized())

        return EconomicRecommendationExperimentDesignRequest(
            approval_request=self.approval_request.normalized(),
            experiment_design_inputs=tuple(normalized_inputs),
            experiment_design_policy=self.experiment_design_policy.normalized(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentDesignRow:
    experiment_reference: str
    approved_recommendation_row: object
    hypothesis: str
    control_definition: str
    treatment_definition: str
    success_measure: str
    observation_window: timedelta
    actor_reference: str
    decision_reference: str
    decided_at: datetime
    design_reference: str
    designed_at: datetime
    recommendation_policy_version: str
    approval_policy_version: str
    experiment_design_policy_version: str
    source_approval_semantics: str
    source_approval_contract_version: str
    experiment_design_semantics: str = ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
    experiment_design_contract_version: str = ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
