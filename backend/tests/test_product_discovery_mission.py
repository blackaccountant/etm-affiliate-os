from app.mission.manager import MissionManager



def test_product_discovery_mission_execution():

    manager = MissionManager()


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