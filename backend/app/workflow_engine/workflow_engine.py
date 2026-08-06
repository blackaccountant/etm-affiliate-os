from app.registry.workflow_registry import WorkflowRegistry


class WorkflowEngine:
    def __init__(self):
        self.registry = WorkflowRegistry()

    def run(self, workflow_name: str, payload: dict):
        workflow = self.registry.get(workflow_name)
        return workflow.execute(payload)