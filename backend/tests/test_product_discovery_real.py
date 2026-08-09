from app.workflows.affiliate.product_discovery_workflow import (
    ProductDiscoveryWorkflow,
)
from app.schemas.affiliate_analysis import AffiliateAnalysis
from app.intelligence.models import IntelligenceResult


class FakeAffiliateDiscovery:

    def execute(self, payload):

        analysis = AffiliateAnalysis(
            company="Test AI Company",
            website=payload["url"],
            category="AI SaaS",
            summary="AI software for testing.",
            target_audience=[
                "Developers",
                "Businesses",
            ],
            pricing_model="Subscription",
            affiliate_program_likely="Yes",
            commission_type="Revenue Share",
            commission_estimate="20%",
            affiliate_score=85,
            recommendation="Strong affiliate opportunity.",
        )

        intelligence = IntelligenceResult(
            score=85,
            grade="A",
            confidence=90,
            reasons=[],
            summary=analysis.summary,
            recommendation=analysis.recommendation,
        )

        class FakeResult:

            success = True

            workflow = "affiliate_discovery"

            data = {
                "analysis": analysis,
                "intelligence": intelligence,
                "database": None,
            }

            events = [
                "WorkflowStarted",
                "AnalysisCompleted",
                "ScoringCompleted",
                "DatabaseSaved",
                "WorkflowCompleted",
            ]

            errors = []

        return FakeResult()


def test_product_discovery_real_intelligence_path():

    workflow = ProductDiscoveryWorkflow()

    workflow.affiliate_discovery = (
        FakeAffiliateDiscovery()
    )

    result = workflow.execute(
        {
            "url": "https://example.com"
        }
    )

    assert result.success is True

    assert result.workflow == (
        "product_discovery"
    )

    assert "products" in result.data

    assert len(
        result.data["products"]
    ) == 1

    product = result.data["products"][0]

    assert product["company"] == (
        "Test AI Company"
    )

    assert product["website"] == (
        "https://example.com"
    )

    assert product["affiliate_score"] == 85

    assert product["grade"] == "A"

    assert product["confidence"] == 90