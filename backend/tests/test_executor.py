from app.executor.executor import TaskExecutor
from app.scheduler.scheduler import Scheduler


class SuccessfulWorkflowEngine:
    def __init__(self):
        self.calls = []

    def run(self, workflow_name, payload):
        self.calls.append((workflow_name, payload))
        return {
            "success": True,
            "workflow": workflow_name,
            "data": {"test": True},
            "errors": [],
        }


def test_executor_runs_workflow():
    scheduler = Scheduler()
    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )
    engine = SuccessfulWorkflowEngine()
    executor = TaskExecutor()
    executor.engine = engine
    result = executor.execute(task)
    assert result is not None
    assert result["success"] is True
    assert result["workflow"] == "affiliate_discovery"
    assert task.status == "COMPLETED"
    assert engine.calls == [("affiliate_discovery", task.payload)]
