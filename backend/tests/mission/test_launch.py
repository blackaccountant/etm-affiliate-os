from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo


def test_launch_mission():

    workforce = WorkforceManager()

    workforce.register(
        WorkerInfo(
            name="Product Hunter",
            worker_type="Research",
            status="ONLINE",
        )
    )

    manager = MissionManager(
        workforce=workforce,
    )

    launch = manager.launch(
        name="Affiliate Discovery",
        objective="Find profitable affiliate products",
        workflow="affiliate_discovery",
    )

    assert launch["mission"] is not None

    assert launch["worker"] is not None

    assert (
        launch["worker"].status
        ==
        "BUSY"
    )