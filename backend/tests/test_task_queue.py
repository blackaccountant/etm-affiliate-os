from app.task_queue.queue import TaskQueue
from app.task_queue.task import Task


def test_task_queue_enqueue_and_dequeue():

    queue = TaskQueue()

    task = Task(
        workflow_name="affiliate_discovery",
        payload={},
    )

    queue.enqueue(task)

    assert queue.size() == 1

    result = queue.dequeue()

    assert result.workflow_name == "affiliate_discovery"

    assert queue.is_empty()


def test_task_queue_priority():

    queue = TaskQueue()

    low = Task(
        workflow_name="low",
        payload={},
        priority=1,
    )

    high = Task(
        workflow_name="high",
        payload={},
        priority=10,
    )

    medium = Task(
        workflow_name="medium",
        payload={},
        priority=5,
    )

    queue.enqueue(low)
    queue.enqueue(high)
    queue.enqueue(medium)

    assert queue.dequeue().workflow_name == "high"

    assert queue.dequeue().workflow_name == "medium"

    assert queue.dequeue().workflow_name == "low"


def test_task_queue_peek():

    queue = TaskQueue()

    task = Task(
        workflow_name="affiliate_discovery",
        payload={},
        priority=8,
    )

    queue.enqueue(task)

    assert queue.peek().workflow_name == "affiliate_discovery"

    assert queue.size() == 1


def test_task_queue_empty():

    queue = TaskQueue()

    assert queue.dequeue() is None

    assert queue.peek() is None

    assert queue.is_empty()


def test_task_queue_clear():

    queue = TaskQueue()

    queue.enqueue(
        Task(
            workflow_name="one",
            payload={},
        )
    )

    queue.enqueue(
        Task(
            workflow_name="two",
            payload={},
        )
    )

    assert queue.size() == 2

    queue.clear()

    assert queue.is_empty()