from app.mission.manager import MissionManager
from app.system.runtime import RuntimeAdapter


def test_mission_execution_reports_to_runtime(db_session_factory):

    runtime = RuntimeAdapter()

    manager = MissionManager(
        runtime=runtime,
        workforce=runtime.workforce,
        session_factory=db_session_factory,
    )

    result = manager.launch(
        name="ProductDiscovery",
        objective="Discover profitable affiliate products",
        workflow="product_discovery",
        metadata={},
    )

    assert result["result"].success is True

    history = runtime.get_history()

    assert len(history) > 0

    assert history[-1]["workflow"] == "product_discovery"

    assert history[-1]["status"] == "COMPLETED"
