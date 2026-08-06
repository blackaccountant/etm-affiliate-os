"""
Worker API Endpoints

Expose AI workflows through REST endpoints.
"""

from fastapi import APIRouter

from app.workflow_engine.workflow_engine import WorkflowEngine

router = APIRouter(
    prefix="/workers",
    tags=["AI Workers"],
)


@router.post("/product-hunter")
def run_product_hunter(payload: dict):
    """
    Analyze a company website using the Affiliate Discovery Workflow.
    """

    engine = WorkflowEngine()

    return engine.run(
        workflow_name="affiliate_discovery",
        payload={
            "url": payload.get("url")
        },
    )