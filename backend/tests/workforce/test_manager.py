from app.workforce.manager import WorkforceManager

from app.workforce.worker_info import WorkerInfo


def test_manager_creation():

    manager = WorkforceManager()

    assert manager is not None


def test_register_worker():

    manager = WorkforceManager()

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
    )

    manager.register(worker)

    assert len(manager.workers()) == 1


def test_available_workers():

    manager = WorkforceManager()

    manager.register(
        WorkerInfo(
            name="Product Hunter",
            worker_type="Research",
        )
    )

    available = manager.available_workers()

    assert len(available) == 1