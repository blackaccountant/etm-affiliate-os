"""
Retry Scanner

Finds persisted retryable executions,
claims them when supported, and pushes
them back into the task queue.
"""


class RetryScanner:

    def __init__(
        self,
        execution_service,
        scheduler,
    ):

        self.execution_service = execution_service

        self.scheduler = scheduler


    # ==================================================
    # Scan and Queue Retries
    # ==================================================

    def scan_once(
        self,
        limit: int = 10,
    ):

        retryable = (
            self.execution_service
            .get_retry_queue(
                limit=limit
            )
        )


        queued = []


        for execution in retryable:


            # ------------------------------------------
            # Claim retry if supported
            # ------------------------------------------

            if hasattr(
                self.execution_service,
                "claim_retry",
            ):

                claimed = (
                    self.execution_service
                    .claim_retry(
                        execution
                    )
                )

            else:

                claimed = execution



            if not claimed:

                continue



            # ------------------------------------------
            # Create retry task
            # ------------------------------------------

            task = self.scheduler.schedule(

                workflow_name=(
                    execution.workflow_name
                ),

                payload={

                    "mission_id": (
                        getattr(
                            execution,
                            "mission_id",
                            None,
                        )
                    ),

                    "execution_id": (
                        getattr(
                            execution,
                            "id",
                            None,
                        )
                    ),

                    "retry_count": (
                        getattr(
                            execution,
                            "retry_count",
                            0,
                        )
                    ),

                    "failure_type": (
                        getattr(
                            execution,
                            "failure_type",
                            None,
                        )
                    ),

                },

            )


            queued.append(
                task
            )


        return queued