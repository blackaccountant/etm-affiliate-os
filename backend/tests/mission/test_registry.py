from app.mission.registry import MissionRegistry

from app.mission.mission import Mission


def test_registry_creation():

    registry = MissionRegistry()

    assert registry is not None


def test_add_mission():

    registry = MissionRegistry()

    mission = Mission(
        name="Affiliate",
        objective="Find products",
        workflow="affiliate_discovery",
    )

    registry.add(mission)

    assert len(registry.all()) == 1


def test_get_mission():

    registry = MissionRegistry()

    mission = Mission(
        name="Affiliate",
        objective="Find products",
        workflow="affiliate_discovery",
    )

    registry.add(mission)

    assert (
        registry.get(mission.id)
        ==
        mission
    )


def test_remove_mission():

    registry = MissionRegistry()

    mission = Mission(
        name="Affiliate",
        objective="Find products",
        workflow="affiliate_discovery",
    )

    registry.add(mission)

    registry.remove(
        mission.id
    )

    assert len(registry.all()) == 0


def test_clear_registry():

    registry = MissionRegistry()

    registry.add(
        Mission(
            name="One",
            objective="A",
            workflow="a",
        )
    )

    registry.add(
        Mission(
            name="Two",
            objective="B",
            workflow="b",
        )
    )

    registry.clear()

    assert len(registry.all()) == 0