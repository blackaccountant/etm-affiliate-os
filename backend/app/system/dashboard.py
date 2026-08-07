"""
Dashboard Service

Provides a single snapshot of ETM Affiliate OS
for Mission Control.
"""


class DashboardService:

    def __init__(
        self,
        runtime,
    ):

        self.runtime = runtime


    def summary(self):

        workers = self.runtime.get_workers()

        executions = self.runtime.get_history()

        events = self.runtime.get_events()

        queue = self.runtime.get_queue_status()

        memory = self.runtime.get_memory_count()


        running = [

            execution

            for execution in executions

            if execution.get("status") == "RUNNING"

        ]


        latest_execution = (

            executions[-1]

            if executions

            else None

        )


        latest_event = (

            events[-1]

            if events

            else None

        )


        return {

            "status": "ONLINE",

            "workers": len(workers),

            "running_missions": len(running),

            "completed_missions": len(executions),

            "queue": queue,

            "memory": memory,

            "events": len(events),

            "latest_execution": latest_execution,

            "latest_event": latest_event,

            "worker_list": workers,

            "execution_history": executions,

            "event_history": events,

        }