from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


class WorkflowRegistry:
    def __init__(self):
        self._workflows = {
            "affiliate_discovery": AffiliateDiscoveryWorkflow(),
        }

    def get(self, workflow_name: str):
        if workflow_name not in self._workflows:
            raise ValueError(f"Workflow '{workflow_name}' is not registered.")

        return self._workflows[workflow_name]

    def register(self, name: str, workflow):
        self._workflows[name] = workflow

    def list(self):
        return list(self._workflows.keys())