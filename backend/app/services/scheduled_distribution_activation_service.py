"""One durable activation pass for due scheduled distribution runs."""

from app.distribution.mission_contracts import (
    CONTENT_DISTRIBUTION_CAPABILITY,
    CONTENT_DISTRIBUTION_MISSION_NAME,
    CONTENT_DISTRIBUTION_WORKFLOW,
    DistributionWorkflowPayload,
    distribution_mission_idempotency_key,
)
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.durable_operation_activation_service import (
    DurableOperationActivationService,
    OperationActivationState,
    SuccessorOperationSpec,
)


class ScheduledDistributionActivationService:
    """Atomically make due schedule intent executable, then optionally dispatch."""

    def __init__(self, session_factory, dispatch=None):
        self.session_factory = session_factory
        self.dispatch = dispatch

    @staticmethod
    def _spec(run_id):
        return SuccessorOperationSpec(
            name=CONTENT_DISTRIBUTION_MISSION_NAME,
            objective="publish approved content to configured destination",
            workflow=CONTENT_DISTRIBUTION_WORKFLOW,
            required_capability=CONTENT_DISTRIBUTION_CAPABILITY,
            idempotency_key=distribution_mission_idempotency_key(run_id),
            payload=DistributionWorkflowPayload(run_id).to_dict(),
        )

    def scan_once(self, batch_size=25):
        activated = []
        for _ in range(batch_size):
            db = self.session_factory()
            try:
                due = DistributionRunRepository(db).lock_due_scheduled(1)
                if not due:
                    break
                run = due[0]
                run.status = "CREATED"
                operation = DurableOperationActivationService(db).activate(self._spec(run.id))
                if operation.state is not OperationActivationState.CREATED:
                    raise RuntimeError("scheduled operation already exists")
                db.commit()
                activated.append(operation)
            except RuntimeError as exc:
                db.rollback()
                if "no eligible worker" not in str(exc):
                    raise
                break
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        if self.dispatch is not None:
            for operation in activated:
                self.dispatch(operation)
        return activated
