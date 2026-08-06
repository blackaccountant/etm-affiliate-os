"""
Execution Repository

Handles storing and retrieving workflow execution history.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.execution import Execution


class ExecutionRepository:

    def __init__(self, db: Session):

        self.db = db


    def create(
        self,
        workflow_name: str,
        status: str = "RUNNING",
    ):

        execution = Execution(
            workflow_name=workflow_name,
            status=status,
            started_at=datetime.now(timezone.utc),
        )

        self.db.add(execution)

        self.db.commit()

        self.db.refresh(execution)

        return execution


    def complete(
        self,
        execution: Execution,
        duration: float,
    ):

        execution.status = "COMPLETED"

        execution.completed_at = datetime.now(timezone.utc)

        execution.duration = duration

        self.db.commit()

        self.db.refresh(execution)

        return execution


    def fail(
        self,
        execution: Execution,
        error: str,
    ):

        execution.status = "FAILED"

        execution.error = error

        execution.completed_at = datetime.now(timezone.utc)

        self.db.commit()

        self.db.refresh(execution)

        return execution


    def list_recent(
        self,
        limit: int = 10,
    ):

        return (
            self.db.query(Execution)
            .order_by(
                Execution.id.desc()
            )
            .limit(limit)
            .all()
        )