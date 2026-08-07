from app.execution.status import ExecutionStatus


def test_execution_status_exists():

    assert (
        ExecutionStatus.RUNNING
        ==
        "RUNNING"
    )


def test_execution_completed():

    assert (
        ExecutionStatus.COMPLETED
        ==
        "COMPLETED"
    )