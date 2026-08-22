from app.mission.mission_result import MissionResult



def test_result_creation():

    result = MissionResult(
        mission_id="123",
        success=True,
        data={
            "products": 10
        },
    )


    assert result.success is True



def test_result_data():

    result = MissionResult(
        mission_id="123",
        success=True,
        data={
            "score": 9
        },
    )


    assert (
        result.data["score"]
        ==
        9
    )



def test_result_to_dict():

    result = MissionResult(
        mission_id="123",
        success=True,
    )


    data = result.to_dict()


    assert (
        data["mission_id"]
        ==
        "123"
    )