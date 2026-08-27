"""
Execution Repository

Handles storing and retrieving workflow
and mission execution history.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.execution import Execution


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


        self.db.commit()

        self.db.refresh(
            execution
        )


        return execution


    # ==================================================
    # Claim Retry
    # ==================================================

    def claim_retry(
        self,
        execution: Execution,
    ):

        updated = (
            self.db.query(
                Execution
            )
            .filter(
                Execution.id
                ==
                execution.id
            )
            .filter(
                Execution.status
                ==
                "QUEUED"
            )
            .update(
                {
                    Execution.status:
                        "RETRYING",
                },
                synchronize_session=False,
            )
        )


        self.db.commit()


        if updated != 1:

            return None


        self.db.refresh(
            execution
        )


        return execution


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