"""Bind frozen M11A11 activation authorization to an existing persisted DistributionRun."""

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_MISSION_NAME,
    CONTENT_DISTRIBUTION_WORKFLOW,
    DistributionWorkflowPayload,
    distribution_mission_idempotency_key,
)
from app.optimization.economic_recommendation_experiment_activation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS,
    EconomicRecommendationExperimentActivationRow,
)
from app.optimization.economic_recommendation_experiment_execution_binding_contracts import (
    EconomicRecommendationExperimentExecutionBindingRow,
    EconomicRecommendationExperimentExecutionBindingRequest,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.durable_operation_activation_service import SuccessorOperationSpec
from app.services.economic_recommendation_experiment_activation_service import (
    EconomicRecommendationExperimentActivationService,
)


class EconomicRecommendationExperimentExecutionBindingService:
    """Read-only binding from M11A11 authorization to a persisted distribution target."""

    def __init__(self, db, *, activation_service=None, distribution_run_repository=None):
        self.db = db
        self._activation_service = (
            EconomicRecommendationExperimentActivationService(db)
            if activation_service is None
            else activation_service
        )
        self._distribution_runs = (
            DistributionRunRepository(db)
            if distribution_run_repository is None
            else distribution_run_repository
        )

    @staticmethod
    def _validate_activation_row(row):
        if type(row) is not EconomicRecommendationExperimentActivationRow:
            raise ValueError("M11A11 activation row type is invalid")
        if (
            row.activation_semantics != ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS
            or row.activation_contract_version != ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION
        ):
            raise ValueError("M11A11 activation lineage is invalid")
        return row

    @classmethod
    def _index_activations(cls, rows):
        if type(rows) is not tuple:
            raise ValueError("M11A11 activation outcome must be a tuple")
        by_reference = {}
        ordered = []
        for row in rows:
            row = cls._validate_activation_row(row)
            if row.activation_reference in by_reference:
                raise ValueError("duplicate activation_reference")
            by_reference[row.activation_reference] = row
            ordered.append(row.activation_reference)
        return by_reference, tuple(ordered)

    @classmethod
    def _bind_rows(cls, activation_rows, normalized):
        by_reference, _ = cls._index_activations(activation_rows)
        seen_activation = set()
        seen_distribution_run_id = set()
        bindings_by_reference = {}

        for binding in normalized.execution_bindings:
            if binding.activation_reference not in by_reference:
                raise ValueError("unknown activation_reference")
            if binding.activation_reference in seen_activation:
                raise ValueError("duplicate activation_reference")
            if binding.distribution_run_id in seen_distribution_run_id:
                raise ValueError("duplicate distribution_run_id")
            seen_activation.add(binding.activation_reference)
            seen_distribution_run_id.add(binding.distribution_run_id)
            bindings_by_reference[binding.activation_reference] = binding

        rows = []
        for row in activation_rows:
            binding = bindings_by_reference.get(row.activation_reference)
            if binding is None:
                continue
            rows.append(
                EconomicRecommendationExperimentExecutionBindingRow(
                    experiment_reference=row.experiment_reference,
                    activation_reference=row.activation_reference,
                    distribution_run_id=binding.distribution_run_id,
                    actor_reference=row.actor_reference,
                    decision_reference=row.decision_reference,
                    authorized_at=row.authorized_at,
                    design_reference=row.design_reference,
                    designed_at=row.designed_at,
                    hypothesis=row.hypothesis,
                    control_definition=row.control_definition,
                    treatment_definition=row.treatment_definition,
                    success_measure=row.success_measure,
                    observation_window=row.observation_window,
                    recommendation_policy_version=row.recommendation_policy_version,
                    approval_policy_version=row.approval_policy_version,
                    experiment_design_policy_version=row.experiment_design_policy_version,
                    activation_policy_version=row.activation_policy_version,
                    source_experiment_design_semantics=row.source_experiment_design_semantics,
                    source_experiment_design_contract_version=row.source_experiment_design_contract_version,
                    source_activation_semantics=row.activation_semantics,
                    source_activation_contract_version=row.activation_contract_version,
                    successor_operation_spec=SuccessorOperationSpec(
                        name=CONTENT_DISTRIBUTION_MISSION_NAME,
                        objective="publish approved content to configured destination",
                        workflow=CONTENT_DISTRIBUTION_WORKFLOW,
                        required_capability=CONTENT_DISTRIBUTION_CAPABILITY,
                        idempotency_key=distribution_mission_idempotency_key(binding.distribution_run_id),
                        payload={"distribution_run_id": binding.distribution_run_id},
                    ),
                )
            )
        return tuple(rows)

    def project(self, request: EconomicRecommendationExperimentExecutionBindingRequest):
        normalized = request.normalized()
        activation_rows = self._activation_service.project(
            normalized.experiment_activation_request,
        )
        if type(activation_rows) is not tuple:
            raise ValueError("M11A11 activation outcome must be a tuple")

        for binding in normalized.execution_bindings:
            if self._distribution_runs.get_by_id(binding.distribution_run_id) is None:
                raise ValueError("distribution_run_id does not exist")

        return self._bind_rows(activation_rows, normalized)
