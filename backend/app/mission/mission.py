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
        mission_id: str | None = None,
        status: MissionStatus = MissionStatus.CREATED,
        created_at=None,
        updated_at=None,
    ):

        self.id = mission_id or str(uuid4())

        self.name = name

        self.objective = objective

        self.workflow = workflow

        self.required_capability = (
            required_capability
        )

        self.status = MissionStatus(status)

        self.metadata = metadata or {}

        self.created_at = created_at or datetime.now(timezone.utc)

        self.updated_at = updated_at or self.created_at

    @classmethod
    def from_record(cls, record):
        import json

        metadata = json.loads(record.input_data) if record.input_data else {}
        return cls(
            name=record.name,
            objective=record.objective,
            workflow=record.workflow_name,
            metadata=metadata,
            required_capability=record.required_capability,
            mission_id=record.id,
            status=MissionStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


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
