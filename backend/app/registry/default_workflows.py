"""
Default Workflow Registration
"""

from app.registry.workflow_registry import WorkflowRegistry

from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


def create_workflow_registry():

    registry = WorkflowRegistry()


    registry.register(
        "affiliate_discovery",
        AffiliateDiscoveryWorkflow(),
    )


    return registry