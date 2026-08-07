"""
System Runtime State

Central storage for Mission Control
runtime information.
"""


from app.system.history import ExecutionHistory
from app.system.event_monitor import EventMonitor


class SystemState:

    def __init__(self):

        self.history = ExecutionHistory()

        self.events = EventMonitor()


    def record_execution(
        self,
        workflow: str,
        status: str,
        duration: float
    ):

        self.history.add(
            {
                "workflow": workflow,
                "status": status,
                "duration": duration,
            }
        )


    def record_event(
        self,
        event: str
    ):

        self.events.publish(
            event
        )


    def executions(self):

        return self.history.all()


    def events_list(self):

        return self.events.all()