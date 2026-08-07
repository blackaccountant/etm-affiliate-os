"""
Workforce Manager

Coordinates the AI workforce for
ETM Affiliate OS.
"""

from app.workforce.registry import WorkforceRegistry
from app.workforce.worker_info import WorkerInfo


class WorkforceManager:

    def __init__(self):

        self.registry = WorkforceRegistry()

    def register(
        self,
        worker: WorkerInfo,
    ):

        return self.registry.register(worker)

    def workers(self):

        return self.registry.all()

    def available_workers(self):

        return [

            worker

            for worker in self.registry.all()

            if worker.status in (
                "ONLINE",
                "OFFLINE",
            )

        ]

    def assign(
        self,
        mission_name: str,
    ):
        """
        Assign the first available worker
        to a mission.
        """

        for worker in self.available_workers():

            worker.start_mission(
                mission_name
            )

            return worker

        return None

    def release(
        self,
        worker_name: str,
        success: bool = True,
    ):
        """
        Release a worker after completing
        a mission.
        """

        worker = self.registry.get(
            worker_name
        )

        if worker is None:

            return None

        worker.finish_mission(
            success=success
        )

        return worker

    def get_worker(
        self,
        worker_name: str,
    ):

        return self.registry.get(
            worker_name
        )

    def online_workers(self):

        return [

            worker

            for worker in self.registry.all()

            if worker.status == "ONLINE"

        ]

    def busy_workers(self):

        return [

            worker

            for worker in self.registry.all()

            if worker.status == "BUSY"

        ]

    def offline_workers(self):

        return [

            worker

            for worker in self.registry.all()

            if worker.status == "OFFLINE"

        ]

    def summary(self):

        return {

            "total": len(
                self.registry.all()
            ),

            "online": len(
                self.online_workers()
            ),

            "busy": len(
                self.busy_workers()
            ),

            "offline": len(
                self.offline_workers()
            ),

        }

    def clear(self):

        self.registry.clear()