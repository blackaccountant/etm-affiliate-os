"""
Priority Task Queue

Thread-safe priority queue for ETM Affiliate OS.

Stores and retrieves tasks based on priority while preserving
the existing TaskQueue API.

The queue remains non-blocking:
    dequeue() returns None when no task is available.

Thread safety is provided through a re-entrant lock so the queue
can safely be accessed by the retry background worker and other
runtime components concurrently.
"""

from typing import List, Optional
from threading import RLock

from app.task_queue.task import Task


class TaskQueue:

    def __init__(self):

        self._queue: List[Task] = []

        self._lock = RLock()


    # ==================================================
    # Enqueue
    # ==================================================

    def enqueue(
        self,
        task: Task,
    ):

        if task is None:

            return None


        with self._lock:

            task.mark_queued()

            self._queue.append(
                task
            )

            # ------------------------------------------
            # Higher priority executes first.
            # ------------------------------------------

            self._queue.sort(

                key=lambda t: t.priority,

                reverse=True,

            )


        return task


    # ==================================================
    # Dequeue
    # ==================================================

    def dequeue(
        self,
    ) -> Optional[Task]:

        with self._lock:

            if not self._queue:

                return None


            task = self._queue.pop(
                0
            )


            return task


    # ==================================================
    # Peek
    # ==================================================

    def peek(
        self,
    ) -> Optional[Task]:

        with self._lock:

            if not self._queue:

                return None


            return self._queue[0]


    # ==================================================
    # Size
    # ==================================================

    def size(
        self,
    ):

        with self._lock:

            return len(
                self._queue
            )


    # ==================================================
    # Empty
    # ==================================================

    def is_empty(
        self,
    ):

        with self._lock:

            return len(
                self._queue
            ) == 0


    # ==================================================
    # Pending Tasks
    # ==================================================

    def pending_tasks(
        self,
    ):

        with self._lock:

            return list(
                self._queue
            )


    # ==================================================
    # Clear
    # ==================================================

    def clear(
        self,
    ):

        with self._lock:

            self._queue.clear()