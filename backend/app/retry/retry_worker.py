"""
Retry Worker

Processes queued retry tasks and sends
them back through the executor.

The worker is intentionally resilient:
an execution failure must not terminate
the retry worker itself.

TaskExecutor remains responsible for:

- executing the workflow
- applying retry policy
- persisting retry state
- persisting permanent failure state

RetryWorker is responsible for:

- retrieving the next queued task
- invoking the executor
- preventing one unhandled execution exception
  from killing the worker loop
"""


class RetryWorker:

    def __init__(
        self,
        scheduler,
        executor,
    ):

        self.scheduler = scheduler

        self.executor = executor


    # ==================================================
    # Process One Retry
    # ==================================================

    def process_once(self):

        task = (
            self.scheduler.next_task()
        )


        if not task:

            return None


        try:

            result = (
                self.executor.execute(
                    task
                )
            )


            return result


        except Exception as exc:

            # --------------------------------------------------
            # TaskExecutor is responsible for persistence.
            #
            # If an exception reaches this boundary, the
            # execution has already gone through the executor's
            # failure handling path or the executor encountered
            # an unexpected infrastructure-level exception.
            #
            # The worker must remain alive.
            # --------------------------------------------------

            print(
                "RetryWorker execution error:",
                str(exc),
            )


            return None


    # ==================================================
    # Pending Tasks
    # ==================================================

    def pending_count(self):

        return (
            self.scheduler.queue.size()
        )