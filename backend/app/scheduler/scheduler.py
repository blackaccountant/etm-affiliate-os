from app.task_queue.queue import TaskQueue
from app.task_queue.task import Task


class Scheduler:

    def __init__(self):
        self.queue = TaskQueue()


    def schedule(
        self,
        workflow_name: str,
        payload: dict,
    ):

        task = Task(
            workflow_name=workflow_name,
            payload=payload,
        )

        task.mark_queued()

        self.queue.enqueue(task)

        return task


    def next_task(self):

        task = self.queue.dequeue()

        if task:
            task.mark_running()

        return task