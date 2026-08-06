from app.scheduler.scheduler import Scheduler


def test_scheduler_creates_task():

    scheduler = Scheduler()

    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )

    assert task is not None
    assert task.workflow_name == "affiliate_discovery"
    assert task.status == "QUEUED"


def test_scheduler_dispatches_task():

    scheduler = Scheduler()

    scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )

    task = scheduler.next_task()

    assert task is not None
    assert task.workflow_name == "affiliate_discovery"
    assert task.status == "RUNNING"


def test_task_lifecycle():

    scheduler = Scheduler()

    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )

    assert task.status == "QUEUED"

    task.mark_completed()

    assert task.status == "COMPLETED"
    assert task.completed_at is not None