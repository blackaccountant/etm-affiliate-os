"""
Mission Definition

Represents an AI operation
managed by ETM Affiliate OS.
"""

from datetime import datetime, timezone

from uuid import uuid4

from app.mission.status import (
    MissionStatus,
    validate_mission_transition,
)


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

        self.status = MissionStatus.CREATED

        self.metadata = metadata or {}

        self.created_at = datetime.now(timezone.utc)

        self.updated_at = self.created_at


    def update_status(
        self,
        status: MissionStatus,
    ):

        target_status = MissionStatus(status)

        validate_mission_transition(
            self.status,
            target_status,
        )

        self.status = target_status

        self.updated_at = datetime.now(timezone.utc)


    def to_dict(self):

        return {

            "id": self.id,

            "name": self.name,

            "objective": self.objective,

            "workflow": self.workflow,

            "required_capability":
                self.required_capability,

            "status": self.status.value,

            "metadata": self.metadata,

            "created_at":
                self.created_at.isoformat(),

            "updated_at":
                self.updated_at.isoformat(),

        }
