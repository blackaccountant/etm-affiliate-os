"""Atomic cancellation for a coherent, not-yet-claimed distribution retry."""

from datetime import datetime, timezone

from app.distribution.mission_contracts import distribution_mission_idempotency_key
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker


class QueuedRetryCancellationService:
    """Cancel only the durable RETRY_WAIT/QUEUED retry lifecycle state."""

    failure_type = "OPERATOR_CANCELLED"
    error = "Operator cancelled queued distribution retry"

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def _locked_rows(self, db, run_id):
        key = distribution_mission_idempotency_key(run_id)
        execution = (
            db.query(Execution)
            .join(MissionRecord, MissionRecord.id == Execution.mission_id)
            .filter(MissionRecord.idempotency_key == key)
            .order_by(Execution.id.desc())
            .with_for_update()
            .first()
        )
        if execution is None:
            raise ValueError("distribution retry execution does not exist")
        mission = db.query(MissionRecord).filter(MissionRecord.id == execution.mission_id).with_for_update().one_or_none()
        worker = db.query(Worker).filter(Worker.name == execution.worker_name).with_for_update().one_or_none()
        run = db.query(DistributionRun).filter(DistributionRun.id == run_id).with_for_update().one_or_none()
        if mission is None or worker is None or run is None:
            raise ValueError("distribution retry lifecycle is corrupt")
        return run, mission, execution, worker

    def _is_cancelled(self, run, mission, execution, worker):
        return (
            run.status == "CANCELLED"
            and mission.status == "FAILED"
            and mission.current_worker_name is None
            and execution.status == "FAILED"
            and execution.next_retry_at is None
            and execution.lease_owner is None
            and execution.lease_expires_at is None
            and execution.failure_type == self.failure_type
            and worker.status == "ONLINE"
            and worker.current_mission_id is None
        )

    def cancel(self, run_id):
        db = self.session_factory()
        try:
            run, mission, execution, worker = self._locked_rows(db, run_id)
            if self._is_cancelled(run, mission, execution, worker):
                db.commit()
                db.refresh(run)
                return run
            if not (
                run.status == "RETRY_WAIT"
                and mission.status == "RETRY_WAIT"
                and mission.current_worker_name == worker.name
                and execution.status == "QUEUED"
                and execution.next_retry_at is not None
                and execution.mission_id == mission.id
                and execution.worker_name == worker.name
                and execution.lease_owner is None
                and execution.lease_expires_at is None
                and worker.status == "BUSY"
                and worker.current_mission_id == mission.id
            ):
                raise ValueError("distribution retry lifecycle is not a coherent queued retry")

            now = self._now()
            run.status = "CANCELLED"
            run.updated_at = now
            mission.status = "FAILED"
            mission.current_worker_name = None
            mission.last_error = self.error
            mission.updated_at = now
            mission.completed_at = now
            execution.status = "FAILED"
            execution.next_retry_at = None
            execution.lease_owner = None
            execution.lease_expires_at = None
            execution.failure_type = self.failure_type
            execution.error = self.error
            execution.completed_at = now
            worker.status = "ONLINE"
            worker.current_mission_id = None
            worker.updated_at = now
            worker.last_released_at = now
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
