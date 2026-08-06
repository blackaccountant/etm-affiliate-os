"""
Worker API Endpoints

Expose AI workers through REST endpoints.
"""

from fastapi import APIRouter

from app.ai.workers.product_hunter import ProductHunterWorker
from app.ai.workers.task import WorkerTask

router = APIRouter(
    prefix="/workers",
    tags=["AI Workers"],
)


@router.post("/product-hunter")
def run_product_hunter(payload: dict):
    """
    Analyze a company website.
    """

    url = payload.get("url")

    worker = ProductHunterWorker()

    task = WorkerTask(
        worker_name="ProductHunter",
        action="analyze_website",
        payload={
            "url": url,
        },
    )

    return worker.execute(task)