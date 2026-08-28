"""
Default Workflow Registration
"""


from app.registry.workflow_registry import WorkflowRegistry


from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


from app.workflows.affiliate.product_discovery_workflow import (
    ProductDiscoveryWorkflow,
)
from app.workflows.affiliate.discovery_run_workflow import (
    AffiliateDiscoveryRunWorkflow,
)



def create_workflow_registry():


    registry = WorkflowRegistry()



    registry.register(

        "affiliate_discovery",

        AffiliateDiscoveryWorkflow(),

    )



    registry.register(

        "product_discovery",

        ProductDiscoveryWorkflow(),

    )

    registry.register(

        "affiliate_discovery_run",

        AffiliateDiscoveryRunWorkflow(),

    )



    return registry
