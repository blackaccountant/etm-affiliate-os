"""
Task Executor

Consumes queued tasks and sends them
to the Workflow Engine.
"""


from app.workflow_engine.workflow_engine import WorkflowEngine


class TaskExecutor:

    def __init__(self):
        self.engine = WorkflowEngine()


    def execute(self, task):

        try:

            result = self.engine.run(
                workflow_name=task.workflow_name,
                payload=task.payload,
            )

            task.mark_completed()

            return result


        except Exception:

            task.mark_failed()

            raise