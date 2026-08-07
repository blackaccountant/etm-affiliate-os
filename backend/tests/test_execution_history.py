from app.system.history import ExecutionHistory


def test_history_creation():

    history = ExecutionHistory()

    assert history is not None


def test_add_execution():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate",
            "status": "CREATED",
            "duration": 0,
        }
    )

    assert len(history.all()) == 1


def test_latest_execution():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate",
            "status": "RUNNING",
            "duration": 0,
        }
    )

    latest = history.latest()

    assert latest["status"] == "RUNNING"


def test_update_status():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate",
            "status": "CREATED",
            "duration": 0,
        }
    )

    history.update_status(
        "affiliate",
        "COMPLETED",
    )

    assert (
        history.latest()["status"]
        ==
        "COMPLETED"
    )


def test_clear_history():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate",
            "status": "SUCCESS",
            "duration": 0,
        }
    )

    history.clear()

    assert len(history.all()) == 0