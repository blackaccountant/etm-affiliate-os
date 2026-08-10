"""
Retry Worker

Processes queued retry tasks and sends
them back through the executor.
"""


class RetryWorker:

    def __init__(
        self,
        scheduler,
        executor,
    ):

        self.scheduler = scheduler

        self.executor = executor


    def process_once(self):

        task = (
            self.scheduler.next_task()
        )


        if not task:

            return None


        result = (
            self.executor.execute(
                task
            )
        )


        return result


    def pending_count(self):

        return (
            self.scheduler.queue.size()
        )