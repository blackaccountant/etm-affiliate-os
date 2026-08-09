"""
Event Monitor

Records runtime events for ETM Affiliate OS.

The legacy API returns event names as strings.
The structured API exposes full event records
for Mission Control.
"""

from datetime import datetime, UTC


class EventMonitor:

    def __init__(self):

        self._events = []

    # --------------------------------------------------
    # Publish
    # --------------------------------------------------

    def publish(
        self,
        event: str,
        event_type: str = "INFO",
        metadata: dict | None = None,
    ):

        record = {
            "event": event,
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

        self._events.append(record)

        return event

    # --------------------------------------------------
    # Legacy API
    #
    # Returns event names only.
    # Existing tests and components depend on this.
    # --------------------------------------------------

    def all(self):

        return [
            record["event"]
            for record in self._events
        ]

    # --------------------------------------------------
    # Structured API
    #
    # Used by Mission Control.
    # --------------------------------------------------

    def records(self):

        return [
            record.copy()
            for record in self._events
        ]

    # --------------------------------------------------
    # Latest legacy event
    # --------------------------------------------------

    def latest(self):

        if not self._events:
            return None

        return self._events[-1]["event"]

    # --------------------------------------------------
    # Latest structured event
    # --------------------------------------------------

    def latest_record(self):

        if not self._events:
            return None

        return self._events[-1].copy()

    # --------------------------------------------------
    # Count
    # --------------------------------------------------

    def count(self):

        return len(self._events)

    # --------------------------------------------------
    # Clear
    # --------------------------------------------------

    def clear(self):

        self._events.clear()