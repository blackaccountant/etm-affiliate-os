"""
Runtime Adapter

Shared runtime bridge for Mission Control.
"""

from app.memory.memory_bus import MemoryBus
from app.task_queue.queue import TaskQueue
from app.system.history import ExecutionHistory
from app.system.event_monitor import EventMonitor


class RuntimeAdapter:

    def __init__(self):

        self.memory = MemoryBus()

        self.queue = TaskQueue()

        self.history = ExecutionHistory()

        self.events = EventMonitor()

    # --------------------------------------------------
    # Memory
    # --------------------------------------------------

    def get_memory_count(self):

        try:

            return len(
                self.memory.all()
            )

        except Exception:

            return 0

    # --------------------------------------------------
    # Queue
    # --------------------------------------------------

    def get_queue_status(self):

        return {
            "pending": self.queue.size(),
            "running": 0,
            "completed": 0,
            "failed": 0,
        }

    # --------------------------------------------------
    # Workers
    # --------------------------------------------------

    def get_workers(self):

        return [
            {
                "name": "Product Hunter",
                "status": "ONLINE",
            }
        ]

    # --------------------------------------------------
    # Events
    # --------------------------------------------------

    def record_event(
        self,
        event,
        event_type="INFO",
        metadata=None,
    ):

        return self.events.publish(
            event=event,
            event_type=event_type,
            metadata=metadata,
        )

    def get_events(self):

        # Legacy string-based API
        return self.events.all()

    def get_event_records(self):

        # Structured Mission Control API
        return self.events.records()

    def get_latest_event(self):

        return self.events.latest()

    def get_latest_event_record(self):

        return self.events.latest_record()

    # --------------------------------------------------
    # Execution History
    # --------------------------------------------------

    def record_execution(
        self,
        execution,
    ):

        self.history.add(
            execution
        )

    def update_execution_status(
        self,
        workflow,
        status,
    ):

        return self.history.update_status(
            workflow,
            status,
        )

    def get_history(self):

        return self.history.all()

    # --------------------------------------------------
    # Mission Results
    # --------------------------------------------------

    def get_latest_mission_result(self):

        return self.memory.get(
            "latest_mission_result"
        )