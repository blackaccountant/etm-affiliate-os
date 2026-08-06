"""
Retry Policy Engine

Controls whether failed tasks should retry.
"""


class RetryPolicy:

    def __init__(
        self,
        max_attempts: int = 3,
    ):

        self.max_attempts = max_attempts


    def should_retry(self, task):

        return task.retry_count < self.max_attempts


    def execute_retry(self, task):

        if self.should_retry(task):

            task.retry()

            return True

        return False