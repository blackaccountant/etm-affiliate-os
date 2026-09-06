"""Read durable distribution execution facts into immutable experiment observations."""

from app.distribution.contracts import DistributionRunStatus
from app.distribution.mission_contracts import distribution_mission_idempotency_key
from app.optimization.economic_recommendation_experiment_execution_observation_contracts import (
    EconomicRecommendationExperimentExecutionObservationRequest,
    EconomicRecommendationExperimentExecutionObservationRow,
    validate_execution_binding_row,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.mission_repository import MissionRepository


class EconomicRecommendationExperimentExecutionObservationService:
    """Pure read/projection boundary for frozen experiment execution bindings."""

    def __init__(
        self,
        db,
        *,
        distribution_run_repository=None,
        mission_repository=None,
        execution_repository=None,
    ):
        self.db = db
        self._distribution_runs = (
            DistributionRunRepository(db)
            if distribution_run_repository is None
            else distribution_run_repository
        )
        self._missions = (
            MissionRepository(db) if mission_repository is None else mission_repository
        )
        self._executions = (
            ExecutionRepository(db) if execution_repository is None else execution_repository
        )

    @staticmethod
    def _classify(distribution_run_status):
        recognized = {status.value for status in DistributionRunStatus}
        if distribution_run_status not in recognized:
            raise ValueError("distribution_run status is invalid")
        if distribution_run_status in {"COMPLETED", "FAILED", "CANCELLED"}:
            terminal = "TERMINAL"
        else:
            terminal = "NON_TERMINAL"
        if distribution_run_status == "COMPLETED":
            outcome = "SUCCESS"
        elif distribution_run_status in {"FAILED", "CANCELLED"}:
            outcome = "FAILURE"
        else:
            outcome = "UNRESOLVED"
        return terminal, outcome

    def project(self, request: EconomicRecommendationExperimentExecutionObservationRequest):
        normalized = request.normalized()
        observations = []
        for row in normalized.execution_binding_rows:
            validated = validate_execution_binding_row(row)
            run = self._distribution_runs.get_by_id(validated.distribution_run_id)
            if run is None:
                raise ValueError("distribution_run_id does not exist")
            if run.id != validated.distribution_run_id:
                raise ValueError("distribution_run_id lineage is invalid")

            expected_key = distribution_mission_idempotency_key(validated.distribution_run_id)
            if validated.successor_operation_spec.idempotency_key != expected_key:
                raise ValueError("M11A12 successor operation idempotency key is invalid")
            if validated.successor_operation_spec.payload != {
                "distribution_run_id": validated.distribution_run_id,
            }:
                raise ValueError("M11A12 successor operation payload is invalid")

            mission = self._missions.get_by_idempotency_key(expected_key)
            if mission is None:
                raise ValueError("distribution mission does not exist")
            if mission.idempotency_key != expected_key:
                raise ValueError("distribution mission lineage is invalid")

            executions = self._executions.get_by_mission_id(mission.id)
            if not executions:
                raise ValueError("distribution mission execution does not exist")
            canonical_execution = executions[0]
            if canonical_execution.mission_id != mission.id:
                raise ValueError("canonical execution lineage is invalid")

            terminal, outcome = self._classify(run.status)
            observations.append(EconomicRecommendationExperimentExecutionObservationRow(
                experiment_reference=validated.experiment_reference,
                activation_reference=validated.activation_reference,
                distribution_run_id=validated.distribution_run_id,
                actor_reference=validated.actor_reference,
                decision_reference=validated.decision_reference,
                authorized_at=validated.authorized_at,
                mission_id=mission.id,
                execution_id=canonical_execution.id,
                mission_status=mission.status,
                execution_status=canonical_execution.status,
                distribution_run_status=run.status,
                external_post_id=run.external_post_id,
                external_url=run.external_url,
                platform=run.platform,
                account_reference=run.account_reference,
                destination=run.destination,
                result_metadata=run.result_metadata,
                failure_category=run.failure_category,
                error_summary=run.error_summary,
                distribution_run_completed_at=run.completed_at,
                execution_completed_at=canonical_execution.completed_at,
                mission_completed_at=mission.completed_at,
                terminal_classification=terminal,
                success_failure_classification=outcome,
                execution_observation_policy_version=(
                    normalized.execution_observation_policy.policy_version
                ),
            ))
        return tuple(observations)
