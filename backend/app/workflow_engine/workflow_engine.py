"""
Workflow Engine

Executes registered workflows dynamically.
"""


from app.registry.default_workflows import (
    create_workflow_registry,
)


class WorkflowEngine:

    def __init__(self):

        self.registry = create_workflow_registry()


    def run(
        self,
        workflow_name: str,
        payload: dict,
    ):

        workflow = self.registry.get(
            workflow_name
        )

        if workflow is None:

            raise ValueError(
                f"Workflow '{workflow_name}' not found"
            )

        return workflow.execute(payload)