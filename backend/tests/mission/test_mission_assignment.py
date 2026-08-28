from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo


def test_assign_worker_to_mission(db_session_factory):

    workforce = WorkforceManager()

    workforce.register(
        WorkerInfo(
            name="Product Hunter",
            worker_type="Research",
            status="ONLINE",
        )
    )

    manager = MissionManager(
        session_factory=db_session_factory,
    )

    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find profitable affiliate products",
        workflow="affiliate_discovery",
    )

    worker = workforce.assign(
        mission.name
    )

    assert worker is not None

    assert worker.current_mission == mission.name

    assert worker.status == "BUSY"
