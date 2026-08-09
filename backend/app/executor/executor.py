"""
Task Executor

Executes workflows and reports lifecycle
updates to the shared runtime.
"""

from time import perf_counter

from app.workflow_engine.workflow_engine import WorkflowEngine
from app.memory.memory_bus import MemoryBus


class TaskExecutor:

    def __init__(
        self,
        runtime=None,
    ):

        self.engine = WorkflowEngine()

        self.memory = MemoryBus()

        self.runtime = runtime


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
                    "name"
                )

                else str(
                    task.worker
                )

            )


        # --------------------------------------------------
        # CREATED
        # --------------------------------------------------

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

            # --------------------------------------------------
            # RUNNING
            # --------------------------------------------------

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


            # --------------------------------------------------
            # Execute workflow
            # --------------------------------------------------

            result = self.engine.run(
                workflow_name=workflow_name,
                payload=task.payload,
            )


            duration = (
                perf_counter()
                - start
            )


            task.mark_completed()


            # --------------------------------------------------
            # COMPLETED
            # --------------------------------------------------

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


            # --------------------------------------------------
            # Memory
            # --------------------------------------------------

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


            task.mark_failed()


            # --------------------------------------------------
            # FAILED
            # --------------------------------------------------

            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "FAILED",
                )


                self.runtime.record_event(
                    f"{workflow_name} Failed",
                    event_type="ERROR",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "duration": duration,
                        "error": str(exc),
                    },
                )


            self.memory.store(
                "last_execution",
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "FAILED",
                    "duration": duration,
                    "error": str(exc),
                },
            )


            raise