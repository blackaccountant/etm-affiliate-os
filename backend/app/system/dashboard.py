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

        latest_mission_result = (
            self.runtime.get_latest_mission_result()
        )


        # -----------------------------------------
        # Execution Metrics
        # -----------------------------------------

        successful_executions = [

            execution

            for execution in executions

            if execution.get("status")
            in (
                "SUCCESS",
                "COMPLETED",
            )

        ]


        failed_executions = [

            execution

            for execution in executions

            if execution.get("status")
            == "FAILED"

        ]


        running_executions = [

            execution

            for execution in executions

            if execution.get("status")
            == "RUNNING"

        ]


        terminal_executions = (
            len(successful_executions)
            +
            len(failed_executions)
        )


        success_rate = (

            (
                len(successful_executions)
                /
                terminal_executions
            )
            * 100

            if terminal_executions > 0

            else 100.0

        )


        # -----------------------------------------
        # Latest Execution
        # -----------------------------------------

        latest_execution = (

            executions[-1]

            if executions

            else None

        )


        # -----------------------------------------
        # Latest Event
        # -----------------------------------------

        latest_event = (

            events[-1]

            if events

            else None

        )


        # -----------------------------------------
        # Dashboard Snapshot
        # -----------------------------------------

        return {

            "status": "ONLINE",

            "workers": len(workers),

            "running_missions": len(
                running_executions
            ),

            "completed_missions": len(
                successful_executions
            ),

            "total_executions": len(
                executions
            ),

            "successful_executions": len(
                successful_executions
            ),

            "failed_executions": len(
                failed_executions
            ),

            "success_rate": round(
                success_rate,
                2,
            ),

            "queue": queue,

            "memory": memory,

            "events": len(events),

            "latest_execution": latest_execution,

            "latest_event": latest_event,

            "latest_mission_result": (
                latest_mission_result
            ),

            "worker_list": workers,

            "execution_history": executions,

            "event_history": events,

        }