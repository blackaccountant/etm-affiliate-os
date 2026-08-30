"""Trusted durable NOT_FOUND handoff for reconciliation operations."""

import json

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_MISSION_NAME,
    CONTENT_DISTRIBUTION_WORKFLOW,
    DistributionWorkflowPayload,
    distribution_followup_publish_mission_idempotency_key,
)
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.services.durable_operation_activation_service import SuccessorOperationSpec


class DistributionReconcileLifecycleParticipant:
    def apply(self, db, authority, action: str, result):
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or data.get("reconciliation_state") != "NOT_FOUND":
            return None
        if action != "COMPLETED" or result.get("workflow") != "distribution_reconcile":
            raise ExecutionLeaseLostError("invalid reconciliation lifecycle result")
        run_id = data.get("distribution_run_id")
        execution = db.get(Execution, authority.execution_id)
        try:
            payload = json.loads(execution.input_data or "{}") if execution else {}
        except (TypeError, ValueError):
            raise ExecutionLeaseLostError("invalid stored reconciliation input")
        if not isinstance(run_id, str) or payload.get("distribution_run_id") != run_id:
            raise ExecutionLeaseLostError("reconciliation run does not belong to execution")
        run = db.query(DistributionRun).filter(DistributionRun.id == run_id).with_for_update().one_or_none()
        if run is None or run.status != "RECONCILING":
            raise ExecutionLeaseLostError("reconciliation run is no longer owned")
        generation = run.publish_generation + 1
        run.publish_generation = generation
        run.status = "CREATED"
        run.failure_category = None
        run.error_summary = None
        return SuccessorOperationSpec(
            name=CONTENT_DISTRIBUTION_MISSION_NAME,
            objective="publish approved content to configured destination",
            workflow=CONTENT_DISTRIBUTION_WORKFLOW,
            required_capability=CONTENT_DISTRIBUTION_CAPABILITY,
            idempotency_key=distribution_followup_publish_mission_idempotency_key(run_id, generation),
            payload=DistributionWorkflowPayload(run_id).to_dict(),
        )
