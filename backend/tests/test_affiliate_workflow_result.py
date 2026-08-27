from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)

from app.workflow_engine.workflow_result import (
    WorkflowResult,
)


def test_affiliate_workflow_returns_result(monkeypatch):
    class FakeSession:
        def query(self, model):
            return self

        def filter(self, criterion):
            return self

        def first(self):
            return None

        def close(self):
            pass

    class FakeResearchPipeline:
        def analyze(self, url):
            return {"company": "Example", "website": url}

    class FakeDiscoveryService:
        def discover(self, url):
            return {"program": "example-affiliate"}

    class FakeScoringEngine:
        def score(self, analysis, discovery):
            return {"score": 80, "grade": "A"}

    class FakeDecisionEngine:
        def decide(self, intelligence):
            return {"approved": True}

    class FakeProductIntelligenceService:
        def __init__(self, db):
            self.db = db

        def save_analysis(self, analysis, discovery, intelligence):
            return FakeDatabaseResult()

    class FakeDatabaseResult:
        product_id = "product-1"

        def model_dump(self):
            return {"saved": True, "product_id": self.product_id}

    monkeypatch.setattr(
        "app.workflows.affiliate.affiliate_discovery_workflow.SessionLocal",
        FakeSession,
    )
    monkeypatch.setattr(
        "app.workflows.affiliate.affiliate_discovery_workflow.ProductIntelligenceService",
        FakeProductIntelligenceService,
    )
    workflow = AffiliateDiscoveryWorkflow()
    workflow.research_pipeline = FakeResearchPipeline()
    workflow.discovery_service = FakeDiscoveryService()
    workflow.scoring_engine = FakeScoringEngine()
    workflow.decision_engine = FakeDecisionEngine()
    result = workflow.execute(
        {
            "url": "https://example.invalid"
        }
    )

    assert isinstance(
        result,
        WorkflowResult,
    )

    assert result.workflow == "affiliate_discovery"

    assert result.success is True
    assert result.data["analysis"] == {
        "company": "Example",
        "website": "https://example.invalid",
    }
    assert result.data["database"] == {
        "saved": True,
        "product_id": "product-1",
    }
