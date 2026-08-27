"""
Retry Policy Engine

Controls whether failed tasks retry
and calculates retry timing.
"""

from datetime import (
    datetime,
    timedelta,
    timezone,
)


class RetryPolicy:

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_seconds: int = 30,
    ):

        self.max_attempts = (
            max_attempts
        )

        self.base_delay_seconds = (
            base_delay_seconds
        )


    # ==================================================
    # Retry Availability
    # ==================================================

    def should_retry(
        self,
        task,
    ):

        return (
            task.retry_count
            <
            min(
                self.max_attempts,
                task.max_retries,
            )
        )


    # ==================================================
    # Retry Timing
    # ==================================================

    def calculate_next_retry(
        self,
        task,
    ):

        delay = (
            self.base_delay_seconds
            *
            (
                2
                **
                task.retry_count
            )
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


    # ==================================================
    # Execute Retry
    # ==================================================

    def execute_retry(
        self,
        task,
    ):

        # ----------------------------------------------
        # No retry available
        # ----------------------------------------------

        if not self.should_retry(
            task
        ):

            return False


        # ----------------------------------------------
        # Consume retry
        # ----------------------------------------------

        task.retry()


        # ----------------------------------------------
        # Final retry has now been consumed.
        #
        # Example:
        #
        #     2 / 3
        #       ↓
        #     retry()
        #       ↓
        #     3 / 3
        #
        # There is no retry remaining.
        # ----------------------------------------------

        if not self.should_retry(
            task
        ):

            return False


        # ----------------------------------------------
        # Additional retry remains
        # ----------------------------------------------

        return True