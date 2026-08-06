from app.executor.executor import TaskExecutor
from app.scheduler.scheduler import Scheduler


def test_executor_updates_memory():

    scheduler = Scheduler()

    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )

    executor = TaskExecutor()

    executor.execute(task)

    memory = executor.memory.get("last_execution")

    assert memory is not None

    assert memory["status"] == "COMPLETED"

    assert memory["workflow"] == "affiliate_discovery"