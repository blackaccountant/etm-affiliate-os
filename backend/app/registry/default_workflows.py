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
from app.workflows.content.content_generation_workflow import ContentGenerationWorkflow
from app.workflows.content.content_repurposing_workflow import ContentRepurposingWorkflow
from app.workflows.distribution.distribution_publish_workflow import DistributionPublishWorkflow



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

    registry.register("content_generate", ContentGenerationWorkflow())
    registry.register("content_repurpose", ContentRepurposingWorkflow())
    registry.register("distribution_publish", DistributionPublishWorkflow())



    return registry
