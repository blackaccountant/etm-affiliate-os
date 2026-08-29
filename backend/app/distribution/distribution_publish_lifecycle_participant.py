"""Trusted atomic lifecycle participant for safe distribution publish failures."""

import json

from app.distribution.contracts import DistributionFailureCategory, DistributionRunStatus
from app.models.execution import Execution
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.owned_execution_lifecycle import ExecutionLeaseLostError


class DistributionPublishLifecycleParticipant:
    def apply(self, db, authority, action: str, result) -> None:
        data = result.get("data") if isinstance(result, dict) else getattr(result, "data", None)
        errors = result.get("errors") if isinstance(result, dict) else getattr(result, "errors", None)
        if not isinstance(data, dict) or "distribution_failure_category" not in data:
            return
        run_id = data.get("distribution_run_id")
        category = data.get("distribution_failure_category")
        if (
            result.get("workflow") != "distribution_publish"
            or not isinstance(errors, list)
            or action not in {"RETRY_WAIT", "FAILED"}
            or not isinstance(run_id, str)
        ):
            raise ExecutionLeaseLostError("invalid distribution publish lifecycle result")
        try:
            category = DistributionFailureCategory(category)
        except ValueError:
            raise ExecutionLeaseLostError("invalid distribution failure category")
        execution = db.get(Execution, authority.execution_id)
        try:
            stored = json.loads(execution.input_data or "{}") if execution else {}
        except (TypeError, ValueError):
            raise ExecutionLeaseLostError("invalid stored distribution publish input")
        if stored.get("distribution_run_id") != run_id:
            raise ExecutionLeaseLostError("distribution run does not belong to execution")
        if action == "RETRY_WAIT" and not category.retryable:
            raise ExecutionLeaseLostError("non-retryable distribution failure cannot wait")
        DistributionRunRepository(db).transition_owned(
            run_id, authority, expected_statuses=(DistributionRunStatus.PUBLISHING.value,),
            status=action, values={"failure_category": category.value, "error_summary": errors[0] if errors else None},
            commit=False,
        )
