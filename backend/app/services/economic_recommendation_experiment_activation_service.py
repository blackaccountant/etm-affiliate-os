"""Project frozen M11A10 experiment designs into activation authorization only."""

from app.optimization.economic_recommendation_experiment_activation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS,
    EconomicRecommendationExperimentActivationRequest,
    EconomicRecommendationExperimentActivationRow,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS,
    EconomicRecommendationExperimentDesignRow,
)
from app.services.economic_recommendation_experiment_design_service import (
    EconomicRecommendationExperimentDesignService,
)


class EconomicRecommendationExperimentActivationService:
    """Bind external activation authorization to frozen M11A10 designs."""

    def __init__(
        self,
        db,
        *,
        experiment_design_service=None,
    ):
        self._designs = (
            EconomicRecommendationExperimentDesignService(db)
            if experiment_design_service is None
            else experiment_design_service
        )

    @staticmethod
    def _validate_design_row(row):
        if type(row) is not EconomicRecommendationExperimentDesignRow:
            raise ValueError(
                "M11A10 experiment design row type is invalid"
            )

        if (
            row.experiment_design_semantics
            != ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
            or row.experiment_design_contract_version
            != ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
        ):
            raise ValueError(
                "M11A10 experiment design lineage is invalid"
            )

        return row

    @classmethod
    def _index_designs(cls, rows):
        if type(rows) is not tuple:
            raise ValueError(
                "M11A10 experiment design outcome must be a tuple"
            )

        by_reference = {}
        ordered_references = []

        for row in rows:
            row = cls._validate_design_row(row)

            if row.experiment_reference in by_reference:
                raise ValueError(
                    "duplicate M11A10 experiment_reference"
                )

            by_reference[row.experiment_reference] = row
            ordered_references.append(
                row.experiment_reference
            )

        return (
            by_reference,
            tuple(ordered_references),
        )

    @classmethod
    def _bind_decisions(
        cls,
        design_rows,
        normalized,
    ):
        (
            by_reference,
            ordered_references,
        ) = cls._index_designs(
            design_rows
        )

        if not by_reference:
            if normalized.activation_decisions:
                raise ValueError(
                    "activation decisions require "
                    "M11A10 experiment designs"
                )

            return ()

        decisions_by_reference = {}
        seen_activation_references = set()
        seen_decision_references = set()

        for decision in normalized.activation_decisions:
            experiment_reference = (
                decision.experiment_reference
            )

            if experiment_reference not in by_reference:
                raise ValueError(
                    "activation experiment_reference "
                    "is not present in M11A10"
                )

            if experiment_reference in decisions_by_reference:
                raise ValueError(
                    "duplicate activation decision "
                    "for experiment"
                )

            if (
                decision.activation_reference
                in seen_activation_references
            ):
                raise ValueError(
                    "duplicate activation_reference"
                )

            if (
                decision.decision_reference
                in seen_decision_references
            ):
                raise ValueError(
                    "duplicate activation decision_reference"
                )

            source = by_reference[
                experiment_reference
            ]

            if (
                decision.authorized_at
                < source.designed_at
            ):
                raise ValueError(
                    "activation authorization "
                    "predates experiment design"
                )

            if (
                decision.authorized_at
                < source.decided_at
            ):
                raise ValueError(
                    "activation authorization "
                    "predates recommendation approval"
                )

            decisions_by_reference[
                experiment_reference
            ] = decision

            seen_activation_references.add(
                decision.activation_reference
            )

            seen_decision_references.add(
                decision.decision_reference
            )

        rows = []

        for experiment_reference in ordered_references:
            decision = decisions_by_reference.get(
                experiment_reference
            )

            if decision is None:
                continue

            source = by_reference[
                experiment_reference
            ]

            rows.append(
                EconomicRecommendationExperimentActivationRow(
                    experiment_reference=(
                        source.experiment_reference
                    ),
                    activation_reference=(
                        decision.activation_reference
                    ),
                    hypothesis=source.hypothesis,
                    control_definition=(
                        source.control_definition
                    ),
                    treatment_definition=(
                        source.treatment_definition
                    ),
                    success_measure=(
                        source.success_measure
                    ),
                    observation_window=(
                        source.observation_window
                    ),
                    actor_reference=(
                        decision.actor_reference
                    ),
                    decision_reference=(
                        decision.decision_reference
                    ),
                    authorized_at=(
                        decision.authorized_at
                    ),
                    design_reference=(
                        source.design_reference
                    ),
                    designed_at=(
                        source.designed_at
                    ),
                    recommendation_policy_version=(
                        source.recommendation_policy_version
                    ),
                    approval_policy_version=(
                        source.approval_policy_version
                    ),
                    experiment_design_policy_version=(
                        source.experiment_design_policy_version
                    ),
                    activation_policy_version=(
                        normalized
                        .activation_policy
                        .policy_version
                    ),
                    source_experiment_design_semantics=(
                        source.experiment_design_semantics
                    ),
                    source_experiment_design_contract_version=(
                        source.experiment_design_contract_version
                    ),
                    activation_semantics=(
                        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS
                    ),
                    activation_contract_version=(
                        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION
                    ),
                )
            )

        return tuple(rows)

    def project(
        self,
        request: EconomicRecommendationExperimentActivationRequest,
    ):
        normalized = request.normalized()

        design_rows = self._designs.project(
            normalized.experiment_design_request,
        )

        return self._bind_decisions(
            design_rows,
            normalized,
        )
