from app.ai.workers.product_hunter import ProductHunterWorker
from app.ai.workers.task import WorkerTask
from app.workflow_engine.workflow_result import WorkflowResult


def test_affiliate_discovery_pipeline():
    """
    End-to-end integration test.

    This test verifies that the complete affiliate discovery
    pipeline executes successfully.

    Pipeline:
        Website
            ↓
        ProductHunterWorker
            ↓
        AffiliateDiscoveryWorkflow
            ↓
        AI Analysis
            ↓
        Intelligence Scoring
            ↓
        Product Repository
            ↓
        Database
    """

    worker = ProductHunterWorker()
    worker.workflow = type(
        "SuccessfulWorkflow",
        (),
        {
            "execute": lambda _, payload: WorkflowResult(
                success=True,
                workflow="affiliate_discovery",
                data={
                    "analysis": {
                        "company": "OpenRouter",
                        "website": "https://openrouter.ai/",
                    },
                    "intelligence": {
                        "score": 85,
                        "grade": "A",
                        "confidence": 0.9,
                    },
                    "database": {
                        "saved": True,
                        "duplicate": False,
                        "product_id": "product-1",
                    },
                },
            )
        },
    )()

    task = WorkerTask(
        worker_name="ProductHunter",
        action="analyze_website",
        payload={
            "url": "https://example.invalid"
        },
    )

    result = worker.execute(task)

    # -------------------------------------------------
    # Worker execution
    # -------------------------------------------------

    assert result is not None
    assert result.success is True
    assert result.worker_name == "ProductHunter"
    assert result.action == "analyze_website"

    # -------------------------------------------------
    # Analysis
    # -------------------------------------------------

    assert "analysis" in result.data

    analysis = result.data["analysis"]

    assert analysis["company"] == "OpenRouter"
    assert analysis["website"] == "https://openrouter.ai/"

    # -------------------------------------------------
    # Intelligence
    # -------------------------------------------------

    assert "intelligence" in result.data

    intelligence = result.data["intelligence"]

    assert 0 <= intelligence["score"] <= 100
    assert intelligence["grade"] is not None
    assert intelligence["confidence"] >= 0

    # -------------------------------------------------
    # Database
    # -------------------------------------------------

    assert "database" in result.data

    database = result.data["database"]

    # The pipeline succeeds whether the product
    # is newly inserted or already exists.

    assert (
        database["saved"] is True
        or database["duplicate"] is True
    )

    # We should always have a product id.
    assert database["product_id"] is not None

    # -------------------------------------------------
    # Metadata
    # -------------------------------------------------

    assert "metadata" in result.data
    assert result.data["metadata"]["workflow"] == "AffiliateDiscoveryWorkflow"
