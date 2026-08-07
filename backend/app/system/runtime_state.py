"""
Runtime State

Central shared state container
for ETM Affiliate OS.
"""


from app.memory.memory_bus import MemoryBus

from app.task_queue.queue import TaskQueue

from app.system.history import ExecutionHistory

from app.system.event_monitor import EventMonitor



class RuntimeState:


    def __init__(self):

        self.memory = MemoryBus()

        self.queue = TaskQueue()

        self.history = ExecutionHistory()

        self.events = EventMonitor()



    def snapshot(self):

        return {

            "memory": self.memory.all(),

            "queue": self.queue.size(),

            "history": self.history.all(),

            "events": self.events.all(),

        }