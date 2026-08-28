from app.models.worker import Worker
from app.repositories.worker_repository import WorkerRepository
from app.workforce.status import WorkerStatus


def create_worker(repository, name="Product Hunter", **overrides):
    values = {
        "name": name,
        "worker_type": "AI Agent",
        "capabilities": ["product_discovery"],
    }
    values.update(overrides)
    return repository.create(**values)


def test_create_and_read_worker_with_capabilities_and_utc_timestamps(db_session):
    repository = WorkerRepository(db_session)
    worker = create_worker(repository)

    fetched = repository.get_by_name(worker.name)

    assert fetched.name == "Product Hunter"
    assert fetched.capabilities == ["product_discovery"]
    assert fetched.status == WorkerStatus.OFFLINE.value
    assert fetched.created_at.tzinfo is not None
    assert fetched.updated_at.tzinfo is not None


def test_list_online_returns_only_online_workers(db_session):
    repository = WorkerRepository(db_session)
    online = create_worker(
        repository,
        name="Online",
        status=WorkerStatus.ONLINE,
    )
    create_worker(repository, name="Offline")

    assert repository.list_online() == [online]
    assert repository.list_by_status(WorkerStatus.OFFLINE)[0].name == "Offline"


def test_atomic_claim_sets_busy_and_prevents_second_claim(db_session):
    repository = WorkerRepository(db_session)
    create_worker(repository, status=WorkerStatus.ONLINE)

    assert repository.claim("Product Hunter", "mission-1") is True
    assert repository.claim("Product Hunter", "mission-2") is False

    worker = repository.get_by_name("Product Hunter")
    assert worker.status == WorkerStatus.BUSY.value
    assert worker.current_mission_id == "mission-1"
    assert worker.last_assigned_at.tzinfo is not None


def test_atomic_claim_rejects_offline_worker(db_session):
    repository = WorkerRepository(db_session)
    create_worker(repository)

    assert repository.claim("Product Hunter", "mission-1") is False


def test_release_requires_current_mission_and_is_idempotent(db_session):
    repository = WorkerRepository(db_session)
    create_worker(repository, status=WorkerStatus.ONLINE)
    assert repository.claim("Product Hunter", "mission-1") is True

    assert repository.release("Product Hunter", "wrong-mission", success=True) is False
    assert repository.release("Product Hunter", "mission-1", success=True) is True
    assert repository.release("Product Hunter", "mission-1", success=True) is False

    worker = repository.get_by_name("Product Hunter")
    assert worker.status == WorkerStatus.ONLINE.value
    assert worker.current_mission_id is None
    assert worker.missions_completed == 1
    assert worker.missions_failed == 0
    assert worker.success_rate == 100.0
    assert worker.last_released_at.tzinfo is not None


def test_failed_release_updates_metrics_and_success_rate_once(db_session):
    repository = WorkerRepository(db_session)
    create_worker(repository, status=WorkerStatus.ONLINE)
    assert repository.claim("Product Hunter", "mission-1") is True
    assert repository.release("Product Hunter", "mission-1", success=False) is True
    assert repository.claim("Product Hunter", "mission-2") is True
    assert repository.release("Product Hunter", "mission-2", success=True) is True

    worker = repository.get_by_name("Product Hunter")
    assert worker.missions_completed == 2
    assert worker.missions_failed == 1
    assert worker.success_rate == 50.0
    assert db_session.query(Worker).count() == 1
