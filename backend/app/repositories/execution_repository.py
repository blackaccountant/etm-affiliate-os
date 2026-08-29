"""
Execution Repository

Handles storing and retrieving workflow
and mission execution history.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.services.execution_lease import ExecutionLeaseAuthority


class ExecutionLeaseLostError(RuntimeError):
    """Raised when a stale runtime no longer owns an active Execution lease."""


class ExecutionRepository:
    """
    Database access layer for executions.
    """

    def __init__(
        self,
        db: Session,
    ):

        self.db = db


    # ==================================================
    # UTC Helpers
    # ==================================================

    @staticmethod
    def _utc_now():
        """
        Return the current timezone-aware UTC datetime.
        """

        return datetime.now(
            timezone.utc
        )


    @staticmethod
    def _normalize_utc(
        value,
    ):
        """
        Normalize datetime values to timezone-aware UTC.

        Legacy naive values are interpreted as UTC.
        """

        if value is None:

            return None


        if value.tzinfo is None:

            return value.replace(
                tzinfo=timezone.utc
            )


        return value.astimezone(
            timezone.utc
        )


    # ==================================================
    # Create
    # ==================================================

    def create(
        self,
        workflow_name: str,
        status: str = "RUNNING",
        mission_id: str = None,
        mission_name: str = None,
        worker_name: str = None,
        result_data: str = None,
        input_data: str = None,
        retry_count: int = 0,
        max_retries: int = 3,
        next_retry_at=None,
        failure_type: str = None,
        error: str = None,
    ):

        execution = Execution(

            workflow_name=workflow_name,

            status=status,

            mission_id=mission_id,

            mission_name=mission_name,

            worker_name=worker_name,

            result_data=result_data,

            input_data=input_data,

            retry_count=retry_count,

            max_retries=max_retries,

            next_retry_at=(
                self._normalize_utc(
                    next_retry_at
                )
            ),

            failure_type=failure_type,

            error=error,

            started_at=self._utc_now(),
        )


        self.db.add(
            execution
        )

        self.db.commit()

        self.db.refresh(
            execution
        )


        return execution

    def acquire_lease(self, authority: ExecutionLeaseAuthority, lease_seconds: int) -> bool:
        """Acquire an active-attempt lease at the durable ownership boundary."""
        expiry = self._utc_now() + timedelta(seconds=lease_seconds)
        updated = self.db.query(Execution).filter(Execution.id == authority.execution_id).filter(Execution.status.in_(("RUNNING", "RETRYING"))).filter(Execution.lease_owner.is_(None)).filter(Execution.lease_generation == authority.lease_generation - 1).update({Execution.lease_owner: authority.lease_owner, Execution.lease_generation: authority.lease_generation, Execution.lease_expires_at: expiry}, synchronize_session=False)
        self.db.commit()
        return updated == 1

    def renew_lease(self, authority: ExecutionLeaseAuthority, lease_seconds: int) -> bool:
        expiry = self._utc_now() + timedelta(seconds=lease_seconds)
        updated = self.db.query(Execution).filter(Execution.id == authority.execution_id, Execution.status.in_(("RUNNING", "RETRYING")), Execution.lease_owner == authority.lease_owner, Execution.lease_generation == authority.lease_generation).update({Execution.lease_expires_at: expiry}, synchronize_session=False)
        self.db.commit()
        return updated == 1

    def _fenced_terminal(self, authority, values, *, commit=True):
        """Apply a fenced execution mutation without owning the outer transaction.

        ``commit=False`` is the lifecycle-coordinator path: the Execution,
        Mission, and Worker updates then share one transaction.
        """
        updated = self.db.query(Execution).filter(
            Execution.id == authority.execution_id,
            Execution.status.in_(("RUNNING", "RETRYING")),
            Execution.lease_owner == authority.lease_owner,
            Execution.lease_generation == authority.lease_generation,
        ).update(values, synchronize_session=False)
        if updated != 1:
            raise ExecutionLeaseLostError("execution lease ownership was lost")
        self.db.flush()
        if commit:
            self.db.commit()
            return self.get_by_id(authority.execution_id)
        return None

    def complete_owned(self, authority: ExecutionLeaseAuthority, *, duration=0.0,
                       result_data=None, commit=True):
        return self._fenced_terminal(authority, {
            Execution.status: "COMPLETED",
            Execution.completed_at: self._utc_now(),
            Execution.duration: duration,
            Execution.result_data: result_data,
            Execution.next_retry_at: None,
            Execution.failure_type: None,
            Execution.error: None,
            Execution.lease_expires_at: None,
        }, commit=commit)

    def fail_owned(self, authority: ExecutionLeaseAuthority, *, error,
                   failure_type=None, duration=0.0, retry_count=None, commit=True):
        values = {
            Execution.status: "FAILED",
            Execution.completed_at: self._utc_now(),
            Execution.duration: duration,
            Execution.error: error,
            Execution.failure_type: failure_type,
            Execution.next_retry_at: None,
            Execution.lease_expires_at: None,
        }
        if retry_count is not None:
            values[Execution.retry_count] = retry_count
        return self._fenced_terminal(authority, values, commit=commit)

    def schedule_retry_owned(self, authority: ExecutionLeaseAuthority, *, retry_count,
                             max_retries, next_retry_at, failure_type=None,
                             error=None, result_data=None, commit=True):
        return self._fenced_terminal(authority, {
            Execution.status: "QUEUED",
            Execution.completed_at: None,
            Execution.retry_count: retry_count,
            Execution.max_retries: max_retries,
            Execution.next_retry_at: self._normalize_utc(next_retry_at),
            Execution.failure_type: failure_type,
            Execution.error: error,
            Execution.result_data: result_data,
            Execution.lease_owner: None,
            Execution.lease_expires_at: None,
        }, commit=commit)


    # ==================================================
    # Complete
    # ==================================================

    def complete(
        self,
        execution: Execution,
        duration: float = 0.0,
        result_data: str = None,
    ):

        execution.status = "COMPLETED"

        execution.completed_at = (
            self._utc_now()
        )

        execution.duration = duration

        execution.next_retry_at = None

        execution.failure_type = None

        execution.error = None


        if result_data is not None:

            execution.result_data = (
                result_data
            )


        self.db.commit()

        self.db.refresh(
            execution
        )


        return execution


    # ==================================================
    # Fail
    # ==================================================

    def fail(
        self,
        execution: Execution,
        error: str,
        failure_type: str = None,
        duration: float = 0.0,
        retry_count: int = None,
    ):

        execution.status = "FAILED"

        execution.error = error

        execution.failure_type = (
            failure_type
        )

        execution.completed_at = (
            self._utc_now()
        )

        execution.duration = duration

        execution.next_retry_at = None


        if retry_count is not None:

            execution.retry_count = (
                retry_count
            )


        self.db.commit()

        self.db.refresh(
            execution
        )


        return execution


    # ==================================================
    # Schedule Retry
    # ==================================================

    def schedule_retry(
        self,
        execution: Execution,
        retry_count: int,
        max_retries: int = 3,
        next_retry_at=None,
        failure_type: str = None,
        error: str = None,
    ):

        execution.status = "QUEUED"

        execution.retry_count = (
            retry_count
        )

        execution.max_retries = (
            max_retries
        )

        execution.next_retry_at = (
            self._normalize_utc(
                next_retry_at
            )
        )

        execution.failure_type = (
            failure_type
        )

        execution.error = error

        execution.completed_at = None
        execution.lease_owner = None
        execution.lease_expires_at = None


        self.db.commit()

        self.db.refresh(
            execution
        )


        return execution


    # ==================================================
    # Claim Retry
    # ==================================================

    def claim_due_retry(self, execution_id: int):
        """Atomically convert a due queued retry into a leased active attempt."""
        claimed = (
            self.db.query(Execution)
            .filter(Execution.id == execution_id)
            .filter(Execution.status == "QUEUED")
            .filter(Execution.retry_count < Execution.max_retries)
            .filter((Execution.next_retry_at.is_(None)) | (Execution.next_retry_at <= self._utc_now()))
            .with_for_update()
            .one_or_none()
        )
        if claimed is None:
            self.db.rollback()
            return None

        mission = self.db.query(MissionRecord).filter(MissionRecord.id == claimed.mission_id).with_for_update().one_or_none()
        worker = self.db.query(Worker).filter(Worker.name == claimed.worker_name).with_for_update().one_or_none()
        if (
            mission is None
            or mission.status != "RETRY_WAIT"
            or mission.current_worker_name != claimed.worker_name
            or worker is None
            or worker.status != "BUSY"
            or worker.current_mission_id != mission.id
        ):
            self.db.rollback()
            return None

        authority = ExecutionLeaseAuthority.fresh(
            claimed.id, (claimed.lease_generation or 0) + 1,
        )
        now = self._utc_now()
        claimed.status = "RETRYING"
        claimed.next_retry_at = None
        claimed.lease_owner = authority.lease_owner
        claimed.lease_generation = authority.lease_generation
        claimed.lease_expires_at = now + timedelta(seconds=settings.EXECUTION_LEASE_SECONDS)
        mission.status = "RUNNING"
        mission.updated_at = now
        mission.completed_at = None
        self.db.commit()
        self.db.refresh(claimed)
        # Task-only metadata; never serialize this authority into durable input.
        claimed.retry_authority = authority
        return claimed

    def restore_due_retry_claim(self, execution_id: int, error: str) -> bool:
        """Return an undispatched leased claim to its durable retry state."""
        execution = self.db.query(Execution).filter(Execution.id == execution_id).with_for_update().one_or_none()
        if execution is None or execution.status != "RETRYING":
            self.db.rollback()
            return False
        mission = self.db.query(MissionRecord).filter(MissionRecord.id == execution.mission_id).with_for_update().one_or_none()
        if mission is None or mission.status != "RUNNING" or mission.current_worker_name != execution.worker_name:
            self.db.rollback()
            return False
        now = self._utc_now()
        execution.status = "QUEUED"
        execution.next_retry_at = now
        execution.error = error
        execution.lease_owner = None
        execution.lease_expires_at = None
        mission.status = "RETRY_WAIT"
        mission.updated_at = now
        self.db.commit()
        return True


    # ==================================================
    # Get By ID
    # ==================================================

    def get_by_id(
        self,
        execution_id: int,
    ):

        return (
            self.db.query(
                Execution
            )
            .filter(
                Execution.id
                ==
                execution_id
            )
            .first()
        )


    # ==================================================
    # Get By Mission
    # ==================================================

    def get_by_mission_id(
        self,
        mission_id: str,
    ):

        return (
            self.db.query(
                Execution
            )
            .filter(
                Execution.mission_id
                ==
                mission_id
            )
            .order_by(
                Execution.id.desc()
            )
            .all()
        )


    # ==================================================
    # Recent Executions
    # ==================================================

    def list_recent(
        self,
        limit: int = 10,
    ):

        return (
            self.db.query(
                Execution
            )
            .order_by(
                Execution.id.desc()
            )
            .limit(
                limit
            )
            .all()
        )


    # ==================================================
    # Retry Queue
    # ==================================================

    def get_retryable(
        self,
        now=None,
        limit: int = 10,
    ):

        if now is None:

            now = self._utc_now()

        else:

            now = self._normalize_utc(
                now
            )


        return (
            self.db.query(
                Execution
            )

            .filter(
                Execution.status
                ==
                "QUEUED"
            )

            .filter(
                Execution.retry_count
                <
                Execution.max_retries
            )

            .filter(
                (
                    Execution.next_retry_at
                    ==
                    None
                )
                |
                (
                    Execution.next_retry_at
                    <=
                    now
                )
            )

            .order_by(
                Execution.id.asc()
            )

            .limit(
                limit
            )

            .all()
        )
