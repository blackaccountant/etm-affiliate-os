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



    def execute(self, task):

        start = perf_counter()


        if self.runtime:

            self.runtime.record_execution(
                {
                    "workflow": task.workflow_name,
                    "status": "CREATED",
                    "duration": 0,
                }
            )


        try:


            if self.runtime:

                self.runtime.update_execution_status(
                    task.workflow_name,
                    "RUNNING",
                )


            result = self.engine.run(
                workflow_name=task.workflow_name,
                payload=task.payload,
            )


            duration = perf_counter() - start


            task.mark_completed()


            if self.runtime:

                self.runtime.update_execution_status(
                    task.workflow_name,
                    "COMPLETED",
                )


            self.memory.store(
                "last_execution",
                {
                    "workflow": task.workflow_name,
                    "status": "COMPLETED",
                    "duration": duration,
                },
            )


            return result



        except Exception as exc:


            duration = perf_counter() - start


            task.mark_failed()


            if self.runtime:

                self.runtime.update_execution_status(
                    task.workflow_name,
                    "FAILED",
                )


            self.memory.store(
                "last_execution",
                {
                    "workflow": task.workflow_name,
                    "status": "FAILED",
                    "duration": duration,
                    "error": str(exc),
                },
            )


            raise