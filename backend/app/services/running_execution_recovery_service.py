"""Database-authoritative recovery of expired active execution attempts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func

from app.core.config import settings
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.services.execution_lease import ExecutionLeaseAuthority
from app.workforce.status import WorkerStatus


_ACTIVE_EXECUTION_STATUSES = ("RUNNING", "RETRYING")


@dataclass(frozen=True)
class RecoveredExecution:
    abandoned_execution_id: int
    replacement_execution_id: int
    mission_id: str
    mission_name: str
    worker_name: str
    authority: ExecutionLeaseAuthority


class RunningExecutionRecoveryService:
    """Replace one expired, still-owned active execution exactly once.

    The service works only from the durable execution ID and uses a fresh
    session.  It neither invokes workflows nor makes provider decisions.
    """

    def __init__(self, session_factory, lease_seconds=None):
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds or settings.EXECUTION_LEASE_SECONDS

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def recover(self, execution_id: int) -> RecoveredExecution | None:
        db = self.session_factory()
        try:
            # The expiry predicate deliberately uses database current UTC rather
            # than process-local time.  The row lock serializes PostgreSQL
            # recovery contenders; SQLite tests retain the conditional checks.
            abandoned = (
                db.query(Execution)
                .filter(Execution.id == execution_id)
                .filter(Execution.status.in_(_ACTIVE_EXECUTION_STATUSES))
                .filter(Execution.lease_owner.isnot(None))
                .filter(Execution.lease_expires_at.isnot(None))
                .filter(Execution.lease_expires_at <= func.now())
                .with_for_update()
                .one_or_none()
            )
            if abandoned is None:
                db.rollback()
                return None

            mission = db.get(MissionRecord, abandoned.mission_id)
            worker = db.get(Worker, abandoned.worker_name)
            if (
                mission is None
                or mission.status != "RUNNING"
                or worker is None
                or worker.status != WorkerStatus.BUSY.value
                or worker.current_mission_id != mission.id
                or abandoned.mission_id != mission.id
            ):
                db.rollback()
                return None

            newer = (
                db.query(Execution.id)
                .filter(Execution.mission_id == abandoned.mission_id)
                .filter(Execution.id != abandoned.id)
                .filter(Execution.lease_generation > abandoned.lease_generation)
                .first()
            )
            if newer is not None:
                db.rollback()
                return None

            replacement_generation = abandoned.lease_generation + 1
            replacement_owner = uuid4().hex
            replacement = Execution(
                mission_id=abandoned.mission_id,
                mission_name=abandoned.mission_name,
                worker_name=abandoned.worker_name,
                workflow_name=abandoned.workflow_name,
                status="RUNNING",
                input_data=abandoned.input_data,
                retry_count=abandoned.retry_count,
                max_retries=abandoned.max_retries,
                started_at=self._now(),
                lease_owner=replacement_owner,
                lease_generation=replacement_generation,
                lease_expires_at=self._now() + timedelta(seconds=self.lease_seconds),
            )
            # Preserve E1 as an immutable infrastructure-audit event.  Its old
            # owner and generation remain visible; only the live lease expiry is
            # cleared.
            abandoned.status = "ABANDONED"
            abandoned.lease_expires_at = None
            db.add(replacement)
            db.flush()
            db.commit()
            return RecoveredExecution(
                abandoned_execution_id=abandoned.id,
                replacement_execution_id=replacement.id,
                mission_id=mission.id,
                mission_name=mission.name,
                worker_name=worker.name,
                authority=ExecutionLeaseAuthority(
                    replacement.id, replacement_owner, replacement_generation,
                ),
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def recover_and_dispatch(self, execution_id: int, dispatch):
        """Recover durably, then dispatch only the one committed replacement."""
        recovered = self.recover(execution_id)
        if recovered is not None:
            dispatch(recovered)
        return recovered
