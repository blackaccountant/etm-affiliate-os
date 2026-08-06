from app.workflow_engine.workflow_result import WorkflowResult


def test_workflow_result_success():

    result = WorkflowResult(
        success=True,
        workflow="affiliate_discovery",
    )

    assert result.success is True

    assert result.workflow == "affiliate_discovery"


def test_workflow_result_data():

    result = WorkflowResult(
        success=True,
        workflow="affiliate_discovery",
        data={
            "company": "OpenRouter"
        },
    )

    assert result.data["company"] == "OpenRouter"


def test_workflow_result_events():

    result = WorkflowResult(
        success=True,
        workflow="affiliate_discovery",
        events=[
            "WorkflowStarted",
            "WorkflowCompleted",
        ],
    )

    assert len(result.events) == 2