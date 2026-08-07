from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow
)


def test_affiliate_workflow_exists():

    workflow = AffiliateDiscoveryWorkflow()

    assert workflow is not None