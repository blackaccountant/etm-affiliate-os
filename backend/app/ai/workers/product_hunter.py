"""
Product Hunter Worker

Discovers affiliate opportunities from websites
through the Affiliate Discovery Workflow.
"""

from app.ai.workers.base_worker import BaseWorker
from app.ai.workers.task import WorkerTask
from app.ai.workers.result import WorkerResult

from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


class ProductHunterWorker(BaseWorker):
    """
    Product Hunter AI Worker.
    """

    def __init__(self):
        self.workflow = AffiliateDiscoveryWorkflow()

    def run(self, task: WorkerTask):
        """
        Execute product hunting task.
        """

        try:
            result = self.workflow.execute(
                task.payload
            )

            return WorkerResult(
                success=True,
                worker_name="ProductHunter",
                action=task.action,
                message="Affiliate discovery completed.",
                data=result.model_dump(),
                metadata={
                    "workflow": "AffiliateDiscoveryWorkflow"
                },
            )

        except Exception as e:

            return WorkerResult(
                success=False,
                worker_name="ProductHunter",
                action=task.action,
                message="Worker execution failed.",
                data={},
                metadata={},
                error=str(e),
            )


    def execute(self, task: WorkerTask):
        """
        Backwards compatibility.

        Existing tests and callers use execute().
        New architecture uses run().
        """

        return self.run(task)