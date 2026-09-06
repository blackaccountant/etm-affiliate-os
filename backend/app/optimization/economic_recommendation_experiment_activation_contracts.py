"""Read-only activation authorization contracts over frozen M11A10 experiment design."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.optimization.economic_recommendation_experiment_design_contracts import (
    EconomicRecommendationExperimentDesignRequest,
)


ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION = (
    "m11a11-economic-experiment-activation-authorization-v1"
)

ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS = (
    "externally supplied activation authorization bound to one frozen M11A10 "
    "experiment design; preserves deterministic authorization identity and lineage "
    "only; no operation specification, no Mission creation, no Worker claim, "
    "no Execution creation, no lease acquisition, no scheduling, no dispatch, "
    "no platform action, no traffic mutation, no attribution mutation, and no "
    "economic inference"
)


@dataclass(frozen=True)
class EconomicRecommendationExperimentActivationPolicy:
    policy_version: str

    def normalized(self):
        if (
            type(self.policy_version) is not str
            or not self.policy_version.strip()
        ):
            raise ValueError(
                "activation policy version must be nonblank"
            )

        return EconomicRecommendationExperimentActivationPolicy(
            policy_version=self.policy_version.strip(),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentActivationDecision:
    experiment_reference: str
    activation_reference: str
    actor_reference: str
    decision_reference: str
    authorized_at: datetime

    def normalized(self):
        text_values = (
            self.experiment_reference,
            self.activation_reference,
            self.actor_reference,
            self.decision_reference,
        )

        if any(
            type(value) is not str or not value.strip()
            for value in text_values
        ):
            raise ValueError(
                "activation decision text fields must be nonblank"
            )

        if (
            type(self.authorized_at) is not datetime
            or self.authorized_at.tzinfo is None
            or self.authorized_at.utcoffset() != timedelta(0)
        ):
            raise ValueError(
                "authorized_at must be timezone-aware UTC"
            )

        return EconomicRecommendationExperimentActivationDecision(
            experiment_reference=self.experiment_reference.strip(),
            activation_reference=self.activation_reference.strip(),
            actor_reference=self.actor_reference.strip(),
            decision_reference=self.decision_reference.strip(),
            authorized_at=self.authorized_at,
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentActivationRequest:
    experiment_design_request: EconomicRecommendationExperimentDesignRequest
    activation_decisions: tuple
    activation_policy: EconomicRecommendationExperimentActivationPolicy

    def normalized(self):
        if (
            type(self.experiment_design_request)
            is not EconomicRecommendationExperimentDesignRequest
        ):
            raise ValueError(
                "experiment design request is required"
            )

        if type(self.activation_decisions) is not tuple:
            raise ValueError(
                "activation_decisions must be a tuple"
            )

        if (
            type(self.activation_policy)
            is not EconomicRecommendationExperimentActivationPolicy
        ):
            raise ValueError(
                "activation policy is required"
            )

        normalized_decisions = []

        for item in self.activation_decisions:
            if (
                type(item)
                is not EconomicRecommendationExperimentActivationDecision
            ):
                raise ValueError(
                    "invalid activation decision"
                )

            normalized_decisions.append(
                item.normalized()
            )

        return EconomicRecommendationExperimentActivationRequest(
            experiment_design_request=(
                self.experiment_design_request.normalized()
            ),
            activation_decisions=tuple(
                normalized_decisions
            ),
            activation_policy=(
                self.activation_policy.normalized()
            ),
        )


@dataclass(frozen=True)
class EconomicRecommendationExperimentActivationRow:
    experiment_reference: str
    activation_reference: str

    hypothesis: str
    control_definition: str
    treatment_definition: str
    success_measure: str
    observation_window: timedelta

    actor_reference: str
    decision_reference: str
    authorized_at: datetime

    design_reference: str
    designed_at: datetime

    recommendation_policy_version: str
    approval_policy_version: str
    experiment_design_policy_version: str
    activation_policy_version: str

    source_experiment_design_semantics: str
    source_experiment_design_contract_version: str

    activation_semantics: str = (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS
    )

    activation_contract_version: str = (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION
    )
