"""
Retry Policy Engine

Controls whether failed tasks retry
and calculates retry timing.
"""

from datetime import datetime, timezone, timedelta


class RetryPolicy:

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_seconds: int = 30,
    ):

        self.max_attempts = max_attempts

        self.base_delay_seconds = (
            base_delay_seconds
        )


    def should_retry(
        self,
        task,
    ):

        return (
            task.retry_count
            <
            self.max_attempts
        )


    def calculate_next_retry(
        self,
        task,
    ):

        delay = (
            self.base_delay_seconds
            *
            (2 ** task.retry_count)
        )


        return (
            datetime.now(
                timezone.utc
            )
            +
            timedelta(
                seconds=delay
            )
        )


    def execute_retry(
        self,
        task,
    ):

        if self.should_retry(task):

            task.retry()

            return True

        return False