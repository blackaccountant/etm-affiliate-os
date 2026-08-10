from app.retry.retry_manager import RetryManager


class FakeScanner:

    def scan_once(self, limit=10):

        return [
            "task1",
            "task2",
        ]


class FakeWorker:

    def __init__(self):

        self.calls = 0


    def process_once(self):

        self.calls += 1

        return True



def test_retry_manager_processes_retries():

    worker = FakeWorker()

    manager = RetryManager(
        FakeScanner(),
        worker,
    )


    result = manager.process_once()


    assert len(result) == 2

    assert worker.calls == 2