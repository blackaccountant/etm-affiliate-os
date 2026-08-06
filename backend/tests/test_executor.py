from app.executor.executor import TaskExecutor
from app.scheduler.scheduler import Scheduler


def test_executor_runs_workflow():

    scheduler = Scheduler()

    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )

    executor = TaskExecutor()

    result = executor.execute(task)

    assert result is not None

    assert task.status == "COMPLETED"