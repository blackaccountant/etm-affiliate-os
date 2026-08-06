"""
Task Executor

Consumes queued tasks and sends them
to the Workflow Engine.

Records execution history and updates
runtime memory.
"""

from time import perf_counter

from app.workflow_engine.workflow_engine import WorkflowEngine
from app.memory.memory_bus import MemoryBus


class TaskExecutor:

    def __init__(self):

        self.engine = WorkflowEngine()

        self.memory = MemoryBus()

    def execute(self, task):

        start = perf_counter()

        try:

            result = self.engine.run(
                workflow_name=task.workflow_name,
                payload=task.payload,
            )

            duration = perf_counter() - start

            task.mark_completed()

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