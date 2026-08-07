from app.mission.mission import Mission

from app.execution.status import ExecutionStatus



def test_mission_creation():

    mission = Mission(
        name="Affiliate Discovery",
        objective="Find profitable products",
        workflow="affiliate_discovery",
    )


    assert mission.name == "Affiliate Discovery"

    assert (
        mission.status
        ==
        ExecutionStatus.CREATED
    )



def test_mission_update_status():

    mission = Mission(
        name="Test",
        objective="Testing",
        workflow="test",
    )


    mission.update_status(
        ExecutionStatus.RUNNING
    )


    assert (
        mission.status
        ==
        ExecutionStatus.RUNNING
    )



def test_mission_to_dict():

    mission = Mission(
        name="Test",
        objective="Testing",
        workflow="test",
    )


    data = mission.to_dict()


    assert data["workflow"] == "test"