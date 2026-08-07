from app.system.event_monitor import EventMonitor


def test_monitor_exists():

    monitor = EventMonitor()

    assert monitor is not None


def test_publish_event():

    monitor = EventMonitor()

    monitor.publish(
        "WorkflowStarted"
    )

    assert monitor.count() == 1


def test_latest_event():

    monitor = EventMonitor()

    monitor.publish(
        "WorkflowStarted"
    )

    assert monitor.latest() == "WorkflowStarted"


def test_clear_events():

    monitor = EventMonitor()

    monitor.publish(
        "WorkflowStarted"
    )

    monitor.clear()

    assert monitor.count() == 0