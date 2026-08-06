from app.retry.retry_policy import RetryPolicy
from app.task_queue.task import Task


def test_retry_policy_allows_retry():

    policy = RetryPolicy(
        max_attempts=3
    )

    task = Task(
        workflow_name="affiliate_discovery",
        payload={}
    )

    assert policy.should_retry(task) is True


def test_retry_increases_count():

    policy = RetryPolicy(
        max_attempts=3
    )

    task = Task(
        workflow_name="affiliate_discovery",
        payload={}
    )

    result = policy.execute_retry(task)

    assert result is True

    assert task.retry_count == 1

    assert task.status == "QUEUED"


def test_retry_stops_after_limit():

    policy = RetryPolicy(
        max_attempts=2
    )

    task = Task(
        workflow_name="affiliate_discovery",
        payload={}
    )

    policy.execute_retry(task)
    policy.execute_retry(task)

    assert policy.should_retry(task) is False