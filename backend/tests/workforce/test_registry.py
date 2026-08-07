from app.workforce.registry import WorkforceRegistry
from app.workforce.worker_info import WorkerInfo


def test_registry_creation():

    registry = WorkforceRegistry()

    assert registry is not None


def test_register_worker():

    registry = WorkforceRegistry()

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
    )

    registry.register(worker)

    assert len(registry.all()) == 1


def test_get_worker():

    registry = WorkforceRegistry()

    worker = WorkerInfo(
        name="SEO Hunter",
        worker_type="SEO",
    )

    registry.register(worker)

    assert registry.get("SEO Hunter") == worker


def test_remove_worker():

    registry = WorkforceRegistry()

    worker = WorkerInfo(
        name="Publisher",
        worker_type="Publishing",
    )

    registry.register(worker)

    registry.remove("Publisher")

    assert len(registry.all()) == 0


def test_clear_registry():

    registry = WorkforceRegistry()

    registry.register(
        WorkerInfo(
            name="One",
            worker_type="Test",
        )
    )

    registry.register(
        WorkerInfo(
            name="Two",
            worker_type="Test",
        )
    )

    registry.clear()

    assert len(registry.all()) == 0