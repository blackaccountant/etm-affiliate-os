from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo


def test_assign_available_worker():

    manager = WorkforceManager()

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
        status="ONLINE",
    )

    manager.register(worker)

    assigned = manager.assign(
        "Affiliate Discovery"
    )

    assert assigned is worker

    assert assigned.status == "BUSY"

    assert (
        assigned.current_mission
        ==
        "Affiliate Discovery"
    )


def test_no_available_worker():

    manager = WorkforceManager()

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
        status="BUSY",
    )

    manager.register(worker)

    assigned = manager.assign(
        "Affiliate Discovery"
    )

    assert assigned is None