from app.system.state import SystemState


def test_state_exists():

    state = SystemState()

    assert state is not None


def test_record_execution():

    state = SystemState()

    state.record_execution(
        "AffiliateDiscoveryWorkflow",
        "SUCCESS",
        2.4
    )

    data = state.executions()

    assert len(data) == 1

    assert (
        data[0]["workflow"]
        ==
        "AffiliateDiscoveryWorkflow"
    )


def test_record_event():

    state = SystemState()

    state.record_event(
        "WorkflowStarted"
    )

    assert (
        state.events_list()[0]
        ==
        "WorkflowStarted"
    )