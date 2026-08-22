from app.mission.product_discovery import (
    ProductDiscoveryMission,
)

from app.mission.manager import MissionManager


def test_product_discovery_mission_object():

    mission = ProductDiscoveryMission(
        url="https://openrouter.ai"
    )


    assert mission.name == (
        "ProductDiscovery"
    )

    assert mission.workflow == (
        "product_discovery"
    )

    assert (
        mission.required_capability
        ==
        "product_discovery"
    )

    assert (
        mission.metadata["url"]
        ==
        "https://openrouter.ai"
    )



def test_product_discovery_mission_launch():

    manager = MissionManager()


    mission = ProductDiscoveryMission(
        url="https://openrouter.ai"
    )


    result = manager.execute(
        mission
    )


    assert result.success is True

    assert (
        result.data.workflow
        ==
        "product_discovery"
    )