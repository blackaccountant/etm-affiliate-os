"""
Task Model

Defines units of work handled by ETM Affiliate OS.
"""

from datetime import datetime, timezone
from uuid import uuid4


class Task:

    def __init__(
        self,
        workflow_name: str,
        payload: dict,
        priority: int = 5,
        max_retries: int = 3,
        worker=None,
    ):

        self.id = str(uuid4())

        self.workflow_name = workflow_name

        self.payload = payload

        self.priority = priority

        self.worker = worker

        self.status = "CREATED"

        self.retry_count = 0

        self.max_retries = max_retries

        self.created_at = datetime.now(
            timezone.utc
        )

        self.started_at = None

        self.completed_at = None


    def assign_worker(
        self,
        worker,
    ):

        self.worker = worker


    def mark_queued(self):

        self.status = "QUEUED"


    def mark_running(self):

        self.status = "RUNNING"

        self.started_at = datetime.now(
            timezone.utc
        )


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


    def retry(self):

        self.retry_count += 1

        self.status = "QUEUED"


    @property
    def can_retry(self):

        return (
            self.retry_count
            <
            self.max_retries
        )