"""Launch a durable reconciliation generation without provider activity."""

import json

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_RECONCILIATION_MISSION_NAME,
    CONTENT_DISTRIBUTION_RECONCILIATION_WORKFLOW,
    DistributionWorkflowPayload,
    distribution_reconciliation_mission_idempotency_key,
)
from app.mission.manager import MissionManager
from app.models.distribution_run import DistributionRun
from app.models.mission_record import MissionRecord
from app.repositories.mission_repository import MissionRepository
from app.services.content_distribution_mission_launch_service import ContentDistributionMissionLaunchResult
from app.services.durable_operation_activation_service import (
    DurableOperationActivationService,
    OperationActivationState,
    SuccessorOperationSpec,
)


class ContentDistributionReconciliationMissionLaunchService:
    mission_name = CONTENT_DISTRIBUTION_RECONCILIATION_MISSION_NAME
    workflow_name = CONTENT_DISTRIBUTION_RECONCILIATION_WORKFLOW
    required_capability = CONTENT_DISTRIBUTION_CAPABILITY
    objective = "reconcile ambiguous external publish result"

    def __init__(self, mission_manager=None, session_factory=None, dispatch=None):
        self.mission_manager = mission_manager or MissionManager(session_factory=session_factory)
        self.session_factory = session_factory or self.mission_manager.session_factory
        self.dispatch = dispatch

    @staticmethod
    def _result(run_id, mission):
        data = json.loads(mission.result_data) if isinstance(mission.result_data, str) and mission.result_data else mission.result_data
        return ContentDistributionMissionLaunchResult(
            run_id, mission.id, mission.status, mission.workflow_name,
            mission.required_capability, mission.idempotency_key,
            mission.current_worker_name,
            True if mission.status == "COMPLETED" else False if mission.status == "FAILED" else None,
            mission.last_error, data.get("data", data) if isinstance(data, dict) else None,
        )

    def _spec(self, run_id, generation):
        return SuccessorOperationSpec(
            name=self.mission_name,
            objective=self.objective,
            workflow=self.workflow_name,
            required_capability=self.required_capability,
            idempotency_key=distribution_reconciliation_mission_idempotency_key(run_id, generation),
            payload=DistributionWorkflowPayload(run_id).to_dict(),
        )

    def launch(self, run_id):
        """Activate one generation; a supplied dispatcher runs only after commit."""
        db = self.session_factory()
        operation = None
        try:
            run = (
                db.query(DistributionRun)
                .filter(DistributionRun.id == run_id)
                .with_for_update()
                .one_or_none()
            )
            if run is None:
                raise ValueError("distribution run does not exist")
            if run.status not in {"RECONCILIATION_REQUIRED", "RECONCILING"}:
                raise RuntimeError("distribution run is not reconciliation-required")

            missions = MissionRepository(db)
            generation = run.reconciliation_generation
            current = missions.get_by_idempotency_key(
                distribution_reconciliation_mission_idempotency_key(run.id, generation)
            )
            if run.status == "RECONCILING":
                if current is None:
                    raise RuntimeError("reconciling run has no current reconciliation mission")
                db.rollback()
                return self._result(run_id, current)

            if current is not None and current.status in {"COMPLETED", "FAILED"}:
                run.reconciliation_generation += 1
                generation = run.reconciliation_generation
            elif current is not None:
                operation = DurableOperationActivationService(db).activate(self._spec(run.id, generation))
                db.rollback()
                return self._result(run_id, current)

            operation = DurableOperationActivationService(db).activate(self._spec(run.id, generation))
            if operation.state is not OperationActivationState.CREATED:
                db.rollback()
                record = missions.get_by_id(operation.mission_id)
                return self._result(run_id, record)
            db.commit()
            result = self._result(run_id, db.get(MissionRecord, operation.mission_id))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        if self.dispatch is not None:
            self.dispatch(operation)
        return result
