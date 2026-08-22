"""
Scheduled Job Definition
"""


class Job:

    def __init__(
        self,
        name: str,
        workflow_name: str,
        payload: dict,
        interval_seconds: int,
    ):

        self.name = name

        self.workflow_name = workflow_name

        self.payload = payload

        self.interval_seconds = interval_seconds

        self.last_run = None