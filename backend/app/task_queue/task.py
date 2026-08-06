"""
Task Model

Defines units of work handled by the ETM Affiliate OS.
"""

from datetime import datetime, timezone
from uuid import uuid4


class Task:

    def __init__(
        self,
        workflow_name: str,
        payload: dict,
    ):
        self.id = str(uuid4())

        self.workflow_name = workflow_name

        self.payload = payload

        self.status = "CREATED"

        self.created_at = datetime.now(
            timezone.utc
        )

        self.completed_at = None


    def mark_queued(self):

        self.status = "QUEUED"


    def mark_running(self):

        self.status = "RUNNING"


    def mark_completed(self):

        self.status = "COMPLETED"

        self.completed_at = datetime.now(
            timezone.utc
        )


    def mark_failed(self):

        self.status = "FAILED"

        self.completed_at = datetime.now(
            timezone.utc
        )