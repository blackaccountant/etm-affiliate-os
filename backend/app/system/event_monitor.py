"""
Event Monitor

Records runtime events for
Mission Control.
"""


class EventMonitor:

    def __init__(self):

        self._events = []


    def publish(self, event: str):

        self._events.append(
            event
        )


    def all(self):

        return list(
            self._events
        )


    def latest(self):

        if not self._events:

            return None

        return self._events[-1]


    def count(self):

        return len(
            self._events
        )


    def clear(self):

        self._events.clear()