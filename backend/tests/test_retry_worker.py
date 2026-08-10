from app.retry.retry_worker import RetryWorker
from app.scheduler.scheduler import Scheduler


class FakeExecutor:

    def __init__(self):

        self.called = False


    def execute(self, task):

        self.called = True

        return True



def test_retry_worker_processes_queue():

    scheduler = Scheduler()

    executor = FakeExecutor()


    scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={},
    )


    worker = RetryWorker(
        scheduler,
        executor,
    )


    result = worker.process_once()


    assert result is True

    assert executor.called is True