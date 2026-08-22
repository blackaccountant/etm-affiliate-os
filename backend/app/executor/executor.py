"""
Task Executor

Executes workflows and manages task lifecycle,
including retry handling and failure recovery.
"""

from time import perf_counter

from app.workflow_engine.workflow_engine import WorkflowEngine
from app.memory.memory_bus import MemoryBus
from app.retry.retry_policy import RetryPolicy


class TaskExecutor:

    def __init__(
        self,
        runtime=None,
    ):

        self.engine = WorkflowEngine()

        self.memory = MemoryBus()

        self.runtime = runtime

        self.workforce = None

        self.retry_policy = RetryPolicy()


        if runtime:

            self.workforce = getattr(
                runtime,
                "workforce",
                None,
            )


    # ==================================================
    # Worker Completion
    # ==================================================

    def update_worker_status(
        self,
        worker_name,
        success=True,
    ):

        if not self.workforce:

            return


        if not worker_name:

            return


        self.workforce.release(
            worker_name,
            success=success,
        )


    # ==================================================
    # Execute
    # ==================================================

    def execute(
        self,
        task,
    ):

        start = perf_counter()


        workflow_name = (
            task.workflow_name
        )


        worker_name = None


        if getattr(
            task,
            "worker",
            None,
        ):

            worker_name = (

                task.worker.name

                if hasattr(
                    task.worker,
                    "name",
                )

                else str(
                    task.worker
                )

            )


        if self.runtime:

            self.runtime.record_execution(
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "CREATED",
                    "duration": 0.0,
                }
            )


        try:

            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "RUNNING",
                )


                self.runtime.record_event(
                    f"{workflow_name} Started",
                    event_type="RUNNING",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                    },
                )


            result = self.engine.run(
                workflow_name=workflow_name,
                payload=task.payload,
            )


            duration = (
                perf_counter()
                - start
            )


            task.mark_completed()


            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "COMPLETED",
                )


                self.runtime.record_event(
                    f"{workflow_name} Completed",
                    event_type="SUCCESS",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "duration": duration,
                    },
                )


            self.update_worker_status(
                worker_name,
                success=True,
            )


            self.memory.store(
                "last_execution",
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "COMPLETED",
                    "duration": duration,
                },
            )


            return result


        except Exception as exc:


            duration = (
                perf_counter()
                - start
            )


            retrying = self.retry_policy.execute_retry(
                task
            )


            # ==========================================
            # Retry scheduled
            # ==========================================

            if retrying:


                if self.runtime:

                    self.runtime.record_event(
                        f"{workflow_name} Retry Scheduled",
                        event_type="RETRY",
                        metadata={
                            "workflow": workflow_name,
                            "worker": worker_name,
                            "retry_count": task.retry_count,
                            "error": str(exc),
                        },
                    )


                self.memory.store(
                    "last_execution",
                    {
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "status": "RETRYING",
                        "retry_count": task.retry_count,
                        "duration": duration,
                        "error": str(exc),
                    },
                )


                return None


            # ==========================================
            # Permanent failure
            # ==========================================

            task.mark_failed()


            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "FAILED",
                )


                self.runtime.record_event(
                    f"{workflow_name} Failed Permanently",
                    event_type="ERROR",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "duration": duration,
                        "retry_count": task.retry_count,
                        "error": str(exc),
                    },
                )


            self.update_worker_status(
                worker_name,
                success=False,
            )


            self.memory.store(
                "last_execution",
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "FAILED",
                    "duration": duration,
                    "retry_count": task.retry_count,
                    "error": str(exc),
                },
            )


            raise