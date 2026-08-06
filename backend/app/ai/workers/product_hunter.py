"""
Product Hunter Worker

Discovers affiliate opportunities from websites
through the Affiliate Discovery Workflow.
"""

from dataclasses import asdict, is_dataclass

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
        Execute Affiliate Discovery Workflow.
        """

        return self.workflow.execute(
            task.payload
        )


    def execute(self, task: WorkerTask):

        """
        Execute worker and normalize workflow output.
        """

        try:

            workflow_result = self.run(task)


            # ---------------------------------------------
            # Convert WorkflowResult into dictionary
            # ---------------------------------------------

            if hasattr(workflow_result, "model_dump"):

                workflow_result = workflow_result.model_dump()


            elif is_dataclass(workflow_result):

                workflow_result = asdict(
                    workflow_result
                )


            elif not isinstance(workflow_result, dict):

                workflow_result = {
                    "result": workflow_result
                }


            # ---------------------------------------------
            # Extract workflow data
            # ---------------------------------------------

            data = workflow_result.get(
                "data",
                workflow_result
            )


            normalized = {}


            # ---------------------------------------------
            # Serialize nested objects
            # ---------------------------------------------

            for key, value in data.items():


                if hasattr(value, "model_dump"):

                    normalized[key] = value.model_dump()


                elif is_dataclass(value):

                    normalized[key] = asdict(value)


                elif isinstance(value, dict):

                    normalized[key] = value


                elif isinstance(value, list):

                    converted = []

                    for item in value:

                        if hasattr(item, "model_dump"):

                            converted.append(
                                item.model_dump()
                            )

                        elif is_dataclass(item):

                            converted.append(
                                asdict(item)
                            )

                        else:

                            converted.append(item)


                    normalized[key] = converted


                else:

                    normalized[key] = value



            # ---------------------------------------------
            # Metadata contract
            # ---------------------------------------------

            normalized["metadata"] = {
                "workflow": "AffiliateDiscoveryWorkflow"
            }



            return WorkerResult(
                success=True,
                worker_name=task.worker_name,
                action=task.action,
                message="Worker execution completed.",
                data=normalized,
                metadata={
                    "workflow": "AffiliateDiscoveryWorkflow"
                },
            )


        except Exception as exc:


            return WorkerResult(
                success=False,
                worker_name=task.worker_name,
                action=task.action,
                message="Worker execution failed.",
                data={},
                metadata={},
                error=str(exc),
            )