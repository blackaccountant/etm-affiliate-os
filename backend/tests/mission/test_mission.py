from app.mission.mission import Mission
from app.mission.status import MissionStatus



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
        MissionStatus.CREATED
    )



def test_mission_update_status():

    mission = Mission(
        name="Test",
        objective="Testing",
        workflow="test",
    )


    mission.update_status(
        MissionStatus.ASSIGNED
    )

    mission.update_status(
        MissionStatus.RUNNING
    )


    assert (
        mission.status
        ==
        MissionStatus.RUNNING
    )



def test_mission_to_dict():

    mission = Mission(
        name="Test",
        objective="Testing",
        workflow="test",
    )


    data = mission.to_dict()


    assert data["workflow"] == "test"
