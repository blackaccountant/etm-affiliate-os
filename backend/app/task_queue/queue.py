"""
Priority Task Queue

Stores and retrieves tasks based on priority.
"""

from typing import List, Optional

from app.task_queue.task import Task


class TaskQueue:

    def __init__(self):
        self._queue: List[Task] = []

    def enqueue(self, task: Task):

        task.mark_queued()

        self._queue.append(task)

        # Higher priority executes first
        self._queue.sort(
            key=lambda t: t.priority,
            reverse=True,
        )

    def dequeue(self) -> Optional[Task]:

        if self.is_empty():
            return None

        return self._queue.pop(0)

    def peek(self) -> Optional[Task]:

        if self.is_empty():
            return None

        return self._queue[0]

    def size(self):

        return len(self._queue)

    def is_empty(self):

        return len(self._queue) == 0

    def pending_tasks(self):

        return list(self._queue)

    def clear(self):

        self._queue.clear()