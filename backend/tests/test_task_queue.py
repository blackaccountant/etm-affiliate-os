from app.task_queue.queue import TaskQueue


def test_task_queue_enqueue_and_dequeue():

    queue = TaskQueue()

    task = {
        "name": "product_scan"
    }

    queue.enqueue(task)

    result = queue.dequeue()

    assert result == task


def test_task_queue_size():

    queue = TaskQueue()

    queue.enqueue(
        {
            "id": 1
        }
    )

    queue.enqueue(
        {
            "id": 2
        }
    )

    assert queue.size() == 2


def test_task_queue_empty():

    queue = TaskQueue()

    assert queue.is_empty() is True

    queue.enqueue(
        {
            "id": 1
        }
    )

    assert queue.is_empty() is False