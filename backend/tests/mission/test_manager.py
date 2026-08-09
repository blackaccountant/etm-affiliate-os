from app.mission.manager import MissionManager


def test_manager_creation():

    manager = MissionManager()

    assert manager is not None



def test_create_mission():

    manager = MissionManager()

    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find products",
        workflow="affiliate_discovery",
        metadata={
            "url": "https://openrouter.ai"
        },
    )

    assert mission.name == "Affiliate Discovery"
    assert mission.workflow == "affiliate_discovery"



def test_execute_mission():

    manager = MissionManager()

    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find products",
        workflow="affiliate_discovery",
        metadata={
            "url": "https://openrouter.ai"
        },
    )

    result = manager.execute(
        mission
    )

    assert result.success is True



def test_clear():

    manager = MissionManager()

    manager.clear()

    assert len(
        manager.missions()
    ) == 0