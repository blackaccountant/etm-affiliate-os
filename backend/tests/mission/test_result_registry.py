from app.mission.result_registry import ResultRegistry

from app.mission.mission_result import MissionResult



def test_registry_creation():

    registry = ResultRegistry()

    assert registry is not None



def test_add_result():

    registry = ResultRegistry()

    result = MissionResult(
        mission_id="mission-1",
        success=True,
        data={
            "products": 5
        },
    )

    registry.add(result)


    assert len(
        registry.all()
    ) == 1



def test_get_result_by_mission():

    registry = ResultRegistry()


    result = MissionResult(
        mission_id="mission-1",
        success=True,
    )


    registry.add(result)


    results = registry.get_by_mission(
        "mission-1"
    )


    assert len(results) == 1



def test_clear_results():

    registry = ResultRegistry()


    registry.add(
        MissionResult(
            mission_id="1",
            success=True,
        )
    )


    registry.clear()


    assert len(
        registry.all()
    ) == 0