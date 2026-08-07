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
    )

    assert len(manager.missions()) == 1


def test_execute_mission():

    manager = MissionManager()

    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find products",
        workflow="affiliate_discovery",
    )

    result = manager.execute(
        mission
    )

    assert result.success is True

    assert len(
        manager.get_results(
            mission.id
        )
    ) == 1


def test_clear():

    manager = MissionManager()

    mission = manager.create_mission(
        name="Test",
        objective="Testing",
        workflow="affiliate_discovery",
    )

    manager.execute(mission)

    manager.clear()

    assert len(manager.missions()) == 0