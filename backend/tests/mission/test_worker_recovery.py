from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo


def test_worker_recovers_after_failed_mission():

    workforce = WorkforceManager()

    worker = WorkerInfo(
        name="Product Hunter",
        worker_type="Research",
        status="ONLINE",
    )

    workforce.register(
        worker
    )


    manager = MissionManager(
        workforce=workforce,
    )


    worker.start_mission(
        "Failed Mission"
    )


    worker.finish_mission(
        success=False
    )


    assert worker.status == "ONLINE"

    assert worker.current_mission is None

    assert worker.missions_completed == 1

    assert worker.success_rate < 100