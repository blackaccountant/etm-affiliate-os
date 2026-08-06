"""
Product Hunter Worker

Discovers affiliate opportunities from company websites.
"""

from __future__ import annotations

from app.ai.workers.base_worker import BaseWorker
from app.ai.workers.result import WorkerResult
from app.ai.workers.task import WorkerTask
from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


class ProductHunterWorker(BaseWorker):
    """
    Product Hunter AI Worker.
    """

    def __init__(self):
        super().__init__(name="ProductHunter")
        self.workflow = AffiliateDiscoveryWorkflow()

    def run(self, task: WorkerTask) -> WorkerResult:
        """
        Execute Product Hunter.
        """

        url = task.payload.get("url")

        workflow = self.workflow.execute(url)

        return WorkerResult(
            success=True,
            worker_name=self.name,
            action=task.action,
            message="Affiliate discovery completed.",
            data={
                "analysis": workflow.analysis.model_dump(),
                "intelligence": workflow.intelligence.model_dump(),
                "database": workflow.database.model_dump(),
                "metadata": workflow.metadata,
            },
        )