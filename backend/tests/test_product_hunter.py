from app.ai.workers.product_hunter import ProductHunterWorker
from app.ai.workers.task import WorkerTask


def test_product_hunter_worker_creation():

    worker = ProductHunterWorker()

    task = WorkerTask(
        worker_name="ProductHunter",
        action="analyze_website",
        payload={
            "url": "https://openrouter.ai"
        }
    )

    assert worker is not None
    assert task.payload["url"] == "https://openrouter.ai"