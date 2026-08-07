from app.system.history import ExecutionHistory


def test_history_creation():

    history = ExecutionHistory()

    assert history.count() == 0


def test_add_execution():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate_discovery"
        }
    )

    assert history.count() == 1


def test_latest_execution():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate_discovery"
        }
    )

    latest = history.latest()

    assert latest["workflow"] == "affiliate_discovery"


def test_clear_history():

    history = ExecutionHistory()

    history.add(
        {
            "workflow": "affiliate_discovery"
        }
    )

    history.clear()

    assert history.count() == 0