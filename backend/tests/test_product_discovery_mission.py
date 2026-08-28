from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager



def test_product_discovery_mission_execution(db_session_factory):

    manager = MissionManager(
        workforce=WorkforceManager(load_defaults=True),
        session_factory=db_session_factory,
    )


    result = manager.launch(

        name="ProductDiscovery",

        objective="Discover profitable affiliate products",

        workflow="product_discovery",

        metadata={},

    )


    assert result["mission"] is not None


    assert result["result"].success is True


    assert (
        result["result"].data.workflow
        ==
        "product_discovery"
    )
