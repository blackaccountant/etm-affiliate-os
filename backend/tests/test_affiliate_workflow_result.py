from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)

from app.workflow_engine.workflow_result import (
    WorkflowResult,
)


def test_affiliate_workflow_returns_result():

    workflow = AffiliateDiscoveryWorkflow()

    result = workflow.execute(
        {
            "url": "https://openrouter.ai"
        }
    )

    assert isinstance(
        result,
        WorkflowResult,
    )

    assert result.workflow == "affiliate_discovery"

    assert result.success is True