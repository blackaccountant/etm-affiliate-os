"""
Runtime Tracker

Central coordinator for runtime
history and event recording.
"""


from app.system.history import ExecutionHistory
from app.system.event_monitor import EventMonitor


class RuntimeTracker:

    def __init__(self):

        self.history = ExecutionHistory()

        self.events = EventMonitor()


    def record_event(self, event: str):

        self.events.publish(
            event
        )


    def record_execution(
        self,
        execution: dict
    ):

        self.history.add(
            execution
        )


    def get_events(self):

        return self.events.all()


    def get_history(self):

        return self.history.all()


    def clear(self):

        self.events.clear()

        self.history.clear()