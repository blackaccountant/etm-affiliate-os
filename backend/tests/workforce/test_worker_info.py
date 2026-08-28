from app.workforce.worker_info import WorkerInfo
from app.workforce.status import WorkerStatus


def test_worker_creation():

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
    )

    assert worker.status is WorkerStatus.OFFLINE


def test_start_mission():

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
        status=WorkerStatus.ONLINE,
    )

    worker.start_mission(
        "Affiliate Discovery"
    )

    assert worker.status is WorkerStatus.BUSY

    assert (
        worker.current_mission
        ==
        "Affiliate Discovery"
    )


def test_finish_mission():

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
        status=WorkerStatus.ONLINE,
    )

    worker.start_mission(
        "Affiliate Discovery"
    )

    worker.finish_mission()

    assert worker.status is WorkerStatus.ONLINE

    assert (
        worker.missions_completed
        ==
        1
    )


def test_to_dict():

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
    )

    data = worker.to_dict()

    assert data["name"] == "Product Hunter"
