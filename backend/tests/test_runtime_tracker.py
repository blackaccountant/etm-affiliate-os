from app.system.runtime_tracker import RuntimeTracker


def test_tracker_exists():

    tracker = RuntimeTracker()

    assert tracker is not None


def test_record_event():

    tracker = RuntimeTracker()

    tracker.record_event(
        "WorkflowStarted"
    )

    assert (
        tracker.get_events()[0]
        ==
        "WorkflowStarted"
    )


def test_record_execution():

    tracker = RuntimeTracker()

    tracker.record_execution(
        {
            "workflow":
            "affiliate_discovery"
        }
    )

    assert len(
        tracker.get_history()
    ) == 1


def test_clear_tracker():

    tracker = RuntimeTracker()

    tracker.record_event(
        "Test"
    )

    tracker.clear()

    assert tracker.get_events() == []