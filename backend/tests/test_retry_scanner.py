from app.retry.retry_scanner import RetryScanner


class FakeExecution:

    workflow_name = "affiliate_discovery"

    mission_id = "123"

    retry_count = 1

    max_retries = 3

    id = 10

    failure_type = "NETWORK"

    status = "QUEUED"


class FakeExecutionService:

    def __init__(self):

        self.claimed = []

    def get_retry_queue(
        self,
        limit=10,
    ):

        return [
            FakeExecution()
        ]

    def claim_retry(
        self,
        execution,
    ):

        execution.status = "RETRYING"

        self.claimed.append(
            execution
        )

        return execution


class FakeScheduler:

    def __init__(self):

        self.tasks = []

    def schedule(
        self,
        workflow_name,
        payload,
    ):

        task = {
            "workflow": workflow_name,
            "payload": payload,
        }

        self.tasks.append(
            task
        )

        return task


def test_retry_scanner_queues_tasks():

    scheduler = FakeScheduler()

    service = FakeExecutionService()

    scanner = RetryScanner(
        service,
        scheduler,
    )


    result = scanner.scan_once()


    assert len(result) == 1

    assert (
        result[0]["workflow"]
        == "affiliate_discovery"
    )


def test_retry_scanner_claims_execution():

    scheduler = FakeScheduler()

    service = FakeExecutionService()

    scanner = RetryScanner(
        service,
        scheduler,
    )


    scanner.scan_once()


    assert len(
        service.claimed
    ) == 1


    execution = (
        service.claimed[0]
    )


    assert (
        execution.status
        == "RETRYING"
    )


def test_retry_scanner_passes_retry_metadata():

    scheduler = FakeScheduler()

    service = FakeExecutionService()

    scanner = RetryScanner(
        service,
        scheduler,
    )


    scanner.scan_once()


    assert len(
        scheduler.tasks
    ) == 1


    payload = (
        scheduler.tasks[0]["payload"]
    )


    assert (
        payload["mission_id"]
        == "123"
    )


    assert (
        payload["execution_id"]
        == 10
    )


    assert (
        payload["retry_count"]
        == 1
    )


    assert (
        payload["failure_type"]
        == "NETWORK"
    )