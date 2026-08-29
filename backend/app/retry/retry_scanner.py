"""
Retry Scanner

Recovers persisted retryable executions from the database,
atomically claims them, restores their durable input snapshot,
and places retry tasks back into the scheduler.
"""

import json

from datetime import datetime, timezone

from app.scheduler.scheduler import Scheduler
from app.task_queue.task import Task

from app.services.execution_service import ExecutionService


class RetryScanner:
    """
    Scans persisted executions for retries that are due.

    Responsibilities:

    1. Find QUEUED executions eligible for retry.
    2. Atomically claim each execution.
    3. Restore the durable input snapshot.
    4. Attach retry execution metadata.
    5. Schedule the retry task.
    6. Keep failed scheduling attempts from crashing
       the entire scanner.
    """

    def __init__(
        self,
        execution_service: ExecutionService,
        scheduler: Scheduler,
    ):

        self.execution_service = (
            execution_service
        )

        self.scheduler = (
            scheduler
        )


    # ==================================================
    # Restore Input
    # ==================================================

    def _restore_input(
        self,
        execution,
    ):
        """
        Restore the durable input snapshot stored
        on the persisted execution.

        The original payload is preserved.

        If the stored value is a dictionary,
        it becomes the task payload directly.

        Non-dictionary JSON values are wrapped under
        `input_data`.

        Invalid JSON is preserved as raw input_data.
        """

        raw_input = getattr(
            execution,
            "input_data",
            None,
        )


        if not raw_input:

            return {}


        try:

            restored_input = json.loads(
                raw_input
            )

        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):

            return {
                "input_data": raw_input,
            }


        if isinstance(
            restored_input,
            dict,
        ):

            return dict(
                restored_input
            )


        return {
            "input_data": restored_input,
        }


    # ==================================================
    # Retry Metadata
    # ==================================================

    def _build_retry_payload(
        self,
        execution,
    ):
        """
        Restore the durable payload and attach
        operational retry metadata.
        """

        payload = self._restore_input(
            execution
        )


        execution_id = getattr(
            execution,
            "id",
            None,
        )


        mission_id = getattr(
            execution,
            "mission_id",
            None,
        )


        retry_count = getattr(
            execution,
            "retry_count",
            0,
        )


        max_retries = getattr(
            execution,
            "max_retries",
            3,
        )


        failure_type = getattr(
            execution,
            "failure_type",
            None,
        )

        worker_name = getattr(
            execution,
            "worker_name",
            None,
        )


        payload.update(
            {
                "mission_id": mission_id,

                "execution_id": execution_id,

                "retry_count": retry_count,

                "max_retries": max_retries,

                "failure_type": failure_type,
            }
        )
        if worker_name:
            payload["worker_name"] = worker_name


        return payload


    # ==================================================
    # Scan
    # ==================================================

    def scan_once(
        self,
        limit: int = 10,
    ):
        """
        Recover and schedule one batch of retryable
        executions.

        Only executions successfully transitioned
        from QUEUED -> RETRYING are processed.

        Returns:

            list[Task]
        """

        executions = (
            self.execution_service.get_retry_queue(
                limit=limit
            )
        )


        tasks = []


        for candidate in executions:

            # ==========================================
            # Basic validation
            # ==========================================

            workflow_name = getattr(
                candidate,
                "workflow_name",
                None,
            )


            if not workflow_name:

                # No workflow can be scheduled.
                #
                # Do not claim the execution because
                # there is nothing useful we can do
                # with it.

                continue


            # ==========================================
            # ATOMIC CLAIM
            # ==========================================
            #
            # This is the concurrency boundary.
            #
            # Only one worker/process may successfully
            # transition:
            #
            #     QUEUED -> RETRYING
            #
            # If another worker already claimed it,
            # claim_due_retry() returns None.
            # ==========================================

            claimed = self.execution_service.claim_due_retry(candidate.id)


            if claimed is None:

                # Another retry worker won the race.

                continue


            # ==========================================
            # From this point forward, this scanner
            # owns the retry.
            # ==========================================

            execution = claimed


            execution_id = getattr(
                execution,
                "id",
                None,
            )


            workflow_name = getattr(
                execution,
                "workflow_name",
                None,
            )


            # ==========================================
            # Restore durable input
            # ==========================================

            payload = self._build_retry_payload(
                execution
            )


            # ==========================================
            # Schedule retry task
            # ==========================================

            try:

                task = (
                    self.scheduler.schedule(
                        workflow_name=workflow_name,
                        payload=payload,
                    )
                )

            except Exception as exc:

                # --------------------------------------
                # Scheduling failed after the execution
                # was claimed.
                #
                # Do not allow one broken retry to crash
                # the scanner.
                #
                # Return the execution to QUEUED so a
                # future scanner pass can recover it.
                # --------------------------------------

                retry_count = getattr(
                    execution,
                    "retry_count",
                    0,
                )


                max_retries = getattr(
                    execution,
                    "max_retries",
                    3,
                )


                failure_type = getattr(
                    execution,
                    "failure_type",
                    None,
                )


                error = (
                    f"Retry scheduling failed: {exc}"
                )


                try:

                    restore_claim = getattr(self.execution_service, "restore_due_retry_claim", None)
                    if restore_claim is not None:
                        restore_claim(execution.id, error)
                    else:
                        self.execution_service.schedule_retry(
                            execution=execution,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            next_retry_at=datetime.now(timezone.utc),
                            failure_type=failure_type,
                            error=error,
                        )

                except Exception:

                    # If recovery persistence itself fails,
                    # don't hide the original scheduling
                    # failure from the scanner loop.

                    pass


                continue


            # ==========================================
            # Synchronize retry state on Task
            # ==========================================

            if isinstance(
                task,
                Task,
            ):

                # The lease was committed with the scanner claim.  Keep it
                # out of the durable payload but pass it to the coordinator.
                task.execution_authority = getattr(execution, "retry_authority", None)

                task.retry_count = (
                    getattr(
                        execution,
                        "retry_count",
                        0,
                    )
                )


                task.max_retries = (
                    getattr(
                        execution,
                        "max_retries",
                        3,
                    )
                )


            # ==========================================
            # Successful scheduling
            # ==========================================

            tasks.append(
                task
            )


        return tasks
