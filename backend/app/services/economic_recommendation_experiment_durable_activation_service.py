"""Activate a frozen M11A12 execution-binding into a durable operation only."""

from app.models.distribution_run import DistributionRun
from app.optimization.economic_recommendation_experiment_durable_activation_contracts import (
    EconomicRecommendationExperimentDurableActivationRequest,
    validate_execution_binding_row,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.durable_operation_activation_service import (
    DurableOperationActivationService,
    OperationActivationState,
)


class EconomicRecommendationExperimentDurableActivationService:
    """Bind a frozen M11A12 execution-binding to a live durable operation activation."""

    def __init__(self, db, *, activation_service=None, distribution_run_repository=None):
        self.db = db
        self._activation_service = (
            DurableOperationActivationService(db)
            if activation_service is None
            else activation_service
        )
        self._distribution_runs = (
            DistributionRunRepository(db)
            if distribution_run_repository is None
            else distribution_run_repository
        )

    def project(self, request: EconomicRecommendationExperimentDurableActivationRequest):
        normalized = request.normalized()
        rows = normalized.execution_binding_rows
        if type(rows) is not tuple:
            raise ValueError("execution_binding_rows must be a tuple")

        results = []
        for row in rows:
            validated = validate_execution_binding_row(row)
            run = self._distribution_runs.get_by_id(validated.distribution_run_id)
            if run is None:
                raise ValueError("distribution_run_id does not exist")
            if getattr(run, "status", None) != "CREATED":
                raise ValueError("distribution_run_id must be CREATED")
            operation = self._activation_service.activate(validated.successor_operation_spec)
            if operation.state not in {
                OperationActivationState.CREATED,
                OperationActivationState.EXISTING_ACTIONABLE,
                OperationActivationState.EXISTING_TERMINAL,
            }:
                raise ValueError("durable activation state was not preserved")
            results.append(operation)
        return tuple(results)
