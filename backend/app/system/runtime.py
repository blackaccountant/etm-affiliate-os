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



    # -----------------------------
    # Memory
    # -----------------------------

    def get_memory_count(self):

        try:

            return len(
                self.memory.all()
            )

        except Exception:

            return 0



    # -----------------------------
    # Queue
    # -----------------------------

    def get_queue_status(self):

        return {
            "pending": self.queue.size(),
            "running": 0,
            "completed": 0,
            "failed": 0,
        }



    # -----------------------------
    # Workers
    # -----------------------------

    def get_workers(self):

        return [
            {
                "name": "Product Hunter",
                "status": "ONLINE",
            }
        ]



    # -----------------------------
    # Events
    # -----------------------------

    def record_event(
        self,
        event,
    ):

        self.events.publish(event)



    def get_events(self):

        return self.events.all()



    # -----------------------------
    # Execution History
    # -----------------------------

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