from app.workflow_engine.workflow_engine import WorkflowEngine



def test_product_discovery_workflow_execution():

    engine = WorkflowEngine()


    result = engine.run(

        workflow_name="product_discovery",

        payload={},

    )


    assert result.success is True


    assert (
        result.workflow
        ==
        "product_discovery"
    )


    assert (
        "products"
        in result.data
    )


    assert len(
        result.data["products"]
    ) > 0