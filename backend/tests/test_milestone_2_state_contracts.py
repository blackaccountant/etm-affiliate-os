from concurrent.futures import ThreadPoolExecutor

import pytest

from app.mission.mission import Mission
from app.mission.status import MissionStatus
from app.workforce.manager import WorkforceManager
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


def make_mission() -> Mission:
    return Mission(
        name="Test Mission",
        objective="Verify state contracts",
        workflow="test_workflow",
    )


def test_mission_uses_utc_timestamps_and_serializes_status():
    mission = make_mission()

    assert mission.status is MissionStatus.CREATED
    assert mission.created_at.tzinfo is not None
    assert mission.updated_at.tzinfo is not None
    assert mission.to_dict()["status"] == "CREATED"


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (MissionStatus.CREATED, MissionStatus.WAITING_FOR_WORKER),
        (MissionStatus.CREATED, MissionStatus.ASSIGNED),
        (MissionStatus.WAITING_FOR_WORKER, MissionStatus.ASSIGNED),
        (MissionStatus.ASSIGNED, MissionStatus.RUNNING),
        (MissionStatus.RUNNING, MissionStatus.COMPLETED),
        (MissionStatus.RUNNING, MissionStatus.FAILED),
        (MissionStatus.RUNNING, MissionStatus.RETRY_WAIT),
        (MissionStatus.RETRY_WAIT, MissionStatus.RUNNING),
        (MissionStatus.RETRY_WAIT, MissionStatus.FAILED),
    ],
)
def test_mission_allows_documented_transitions(initial, target):
    mission = make_mission()
    mission.status = initial
    previous_updated_at = mission.updated_at

    mission.update_status(target)

    assert mission.status is target
    assert mission.updated_at >= previous_updated_at


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (MissionStatus.CREATED, MissionStatus.RUNNING),
        (MissionStatus.COMPLETED, MissionStatus.RUNNING),
        (MissionStatus.FAILED, MissionStatus.RETRY_WAIT),
    ],
)
def test_mission_rejects_invalid_and_terminal_transitions(initial, target):
    mission = make_mission()
    mission.status = initial

    with pytest.raises(ValueError, match="Invalid mission status transition"):
        mission.update_status(target)


def test_worker_must_be_online_to_start_a_mission():
    worker = WorkerInfo(name="Offline", worker_type="Test")

    with pytest.raises(ValueError, match="Only ONLINE workers"):
        worker.start_mission("Mission")

    assert worker.status is WorkerStatus.OFFLINE
    assert worker.current_mission is None


def test_worker_finish_is_idempotent_and_uses_utc_timestamps():
    worker = WorkerInfo(
        name="Worker",
        worker_type="Test",
        status=WorkerStatus.ONLINE,
    )

    assert worker.created_at.tzinfo is not None
    worker.start_mission("Mission")
    assert worker.finish_mission(success=False) is True
    assert worker.finish_mission(success=False) is False
    assert worker.status is WorkerStatus.ONLINE
    assert worker.missions_completed == 1
    assert worker.success_rate == 95.0
    assert worker.to_dict()["status"] == "ONLINE"


def test_available_workers_excludes_offline_and_busy_workers():
    manager = WorkforceManager()
    online = WorkerInfo("Online", "Test", status=WorkerStatus.ONLINE)
    offline = WorkerInfo("Offline", "Test")
    busy = WorkerInfo("Busy", "Test", status=WorkerStatus.ONLINE)
    busy.start_mission("Existing")

    for worker in (online, offline, busy):
        manager.register(worker)

    assert manager.available_workers() == [online]


def test_capability_assignment_requires_an_online_matching_worker():
    manager = WorkforceManager()
    offline = WorkerInfo("Offline", "Test", capabilities=["research"])
    online = WorkerInfo(
        "Online",
        "Test",
        capabilities=["research"],
        status=WorkerStatus.ONLINE,
    )
    manager.register(offline)
    manager.register(online)

    assert manager.assign_by_capability("Mission", "research") is online
    assert manager.assign_by_capability("Second", "missing") is None


def test_duplicate_worker_registration_is_rejected():
    manager = WorkforceManager()
    manager.register(WorkerInfo("Duplicate", "Test"))

    with pytest.raises(ValueError, match="Worker already registered"):
        manager.register(WorkerInfo("Duplicate", "Test"))


def test_assignment_is_atomic_for_a_single_online_worker():
    manager = WorkforceManager()
    worker = WorkerInfo("Only", "Test", status=WorkerStatus.ONLINE)
    manager.register(worker)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assignments = list(
            executor.map(
                manager.assign,
                ["Mission One", "Mission Two"],
            )
        )

    assert assignments.count(worker) == 1
    assert assignments.count(None) == 1
    assert worker.status is WorkerStatus.BUSY


def test_release_is_idempotent_and_returns_none_for_unknown_workers():
    manager = WorkforceManager()
    worker = WorkerInfo("Worker", "Test", status=WorkerStatus.ONLINE)
    manager.register(worker)
    manager.assign("Mission")

    assert manager.release("Worker") is worker
    assert manager.release("Worker") is worker
    assert worker.missions_completed == 1
    assert worker.status is WorkerStatus.ONLINE
    assert manager.release("Unknown") is None
