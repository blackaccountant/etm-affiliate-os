"""
Workforce Manager

Coordinates the AI workforce for
ETM Affiliate OS.
"""

from app.workforce.registry import WorkforceRegistry
from app.workforce.worker_info import WorkerInfo


class WorkforceManager:
    """
    Manages AI workers, assignments,
    and workforce lifecycle.
    """

    def __init__(
        self,
        load_defaults: bool = False,
    ):

        self.registry = WorkforceRegistry()

        if load_defaults:

            self._load_default_workers()


    # --------------------------------------------------
    # Default Workforce
    # --------------------------------------------------

    def _load_default_workers(self):

        from app.workforce.default_workers import (
            create_default_workers,
        )

        workers = create_default_workers()

        for worker in workers:

            self.register(
                worker
            )


    # --------------------------------------------------
    # Registration
    # --------------------------------------------------

    def register(
        self,
        worker: WorkerInfo,
    ):

        return self.registry.register(
            worker
        )


    def workers(self):

        return self.registry.all()


    # --------------------------------------------------
    # Availability
    # --------------------------------------------------

    def available_workers(self):

        return [

            worker

            for worker in self.registry.all()

            if worker.status in (
                "ONLINE",
                "OFFLINE",
            )

        ]


    # --------------------------------------------------
    # Legacy Assignment
    # --------------------------------------------------

    def assign(
        self,
        mission_name: str,
    ):
        """
        Assign first available worker.
        """

        for worker in self.available_workers():

            worker.start_mission(
                mission_name
            )

            return worker


        return None


    # --------------------------------------------------
    # Capability Assignment
    # --------------------------------------------------

    def assign_by_capability(
        self,
        mission_name: str,
        capability: str,
    ):
        """
        Assign worker matching capability.
        """

        for worker in self.available_workers():

            if worker.has_capability(
                capability
            ):

                worker.start_mission(
                    mission_name
                )

                return worker


        return None


    # --------------------------------------------------
    # Worker Release
    # --------------------------------------------------

    def release(
        self,
        worker_name: str,
        success: bool = True,
    ):

        worker = self.registry.get(
            worker_name
        )


        if worker is None:

            return None


        worker.finish_mission(
            success=success
        )


        return worker


    # --------------------------------------------------
    # Lookup
    # --------------------------------------------------

    def get_worker(
        self,
        worker_name: str,
    ):

        return self.registry.get(
            worker_name
        )


    # --------------------------------------------------
    # Status
    # --------------------------------------------------

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


    # --------------------------------------------------
    # Summary
    # --------------------------------------------------

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


    # --------------------------------------------------
    # Clear
    # --------------------------------------------------

    def clear(self):

        self.registry.clear()