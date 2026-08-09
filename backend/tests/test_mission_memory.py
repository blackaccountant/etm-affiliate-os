from app.mission.manager import MissionManager
from app.system.runtime import RuntimeAdapter



def test_mission_result_saved_to_runtime_memory():

    runtime = RuntimeAdapter()


    manager = MissionManager(
        runtime=runtime
    )


    manager.launch(

        name="ProductDiscovery",

        objective="Discover affiliate opportunities",

        workflow="product_discovery",

        metadata={},

    )


    stored = runtime.memory.get(
        "latest_mission_result"
    )


    assert stored is not None


    assert (
        stored["workflow"]
        ==
        "product_discovery"
    )


    assert (
        stored["success"]
        is True
    )


    assert (
        "data"
        in stored
    )