"""
Mission Definition

Represents an AI operation
managed by ETM Affiliate OS.
"""

from datetime import datetime

from uuid import uuid4

from app.execution.status import ExecutionStatus


class Mission:

    def __init__(
        self,
        name: str,
        objective: str,
        workflow: str,
        metadata: dict | None = None,
        required_capability: str | None = None,
    ):

        self.id = str(uuid4())

        self.name = name

        self.objective = objective

        self.workflow = workflow

        self.required_capability = (
            required_capability
        )

        self.status = ExecutionStatus.CREATED

        self.metadata = metadata or {}

        self.created_at = datetime.now()


    def update_status(
        self,
        status: ExecutionStatus,
    ):

        self.status = status


    def to_dict(self):

        return {

            "id": self.id,

            "name": self.name,

            "objective": self.objective,

            "workflow": self.workflow,

            "required_capability":
                self.required_capability,

            "status": self.status,

            "metadata": self.metadata,

            "created_at":
                self.created_at.isoformat(),

        }