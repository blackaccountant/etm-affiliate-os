"""Workforce orchestration with in-process assignment protection."""

from threading import RLock

from app.workforce.registry import WorkforceRegistry
from app.workforce.status import WorkerStatus
from app.workforce.worker_info import WorkerInfo


class WorkforceManager:
    """Manages AI workers, assignments, and workforce lifecycle."""

    def __init__(
        self,
        load_defaults: bool = False,
    ):
        self.registry = WorkforceRegistry()
        self._lock = RLock()

        if load_defaults:
            self._load_default_workers()

    def _load_default_workers(self):
        from app.workforce.default_workers import create_default_workers

        for worker in create_default_workers():
            self.register(worker)

    def register(
        self,
        worker: WorkerInfo,
    ):
        with self._lock:
            return self.registry.register(worker)

    def workers(self):
        with self._lock:
            return self.registry.all()

    def available_workers(self):
        with self._lock:
            return [
                worker
                for worker in self.registry.all()
                if worker.status is WorkerStatus.ONLINE
            ]

    def assign(
        self,
        mission_name: str,
    ):
        """Atomically assign the first online worker."""
        with self._lock:
            for worker in self.registry.all():
                if worker.status is not WorkerStatus.ONLINE:
                    continue

                worker.start_mission(mission_name)
                return worker

            return None

    def assign_by_capability(
        self,
        mission_name: str,
        capability: str,
    ):
        """Atomically assign an online worker with the requested capability."""
        with self._lock:
            for worker in self.registry.all():
                if (
                    worker.status is WorkerStatus.ONLINE
                    and worker.has_capability(capability)
                ):
                    worker.start_mission(mission_name)
                    return worker

            return None

    def claim_durable(self, mission_name, capability, claim):
        """Keep local selection synchronized with the durable claim boundary."""
        with self._lock:
            for worker in self.registry.all():
                if worker.status is not WorkerStatus.ONLINE:
                    continue
                if capability and not worker.has_capability(capability):
                    continue
                if not claim(worker):
                    continue
                worker.start_mission(mission_name)
                return worker
            return None

    def release(
        self,
        worker_name: str,
        success: bool = True,
    ):
        with self._lock:
            worker = self.registry.get(worker_name)

            if worker is None:
                return None

            worker.finish_mission(success=success)
            return worker

    def sync_from_durable(self, durable_worker, mission_name=None):
        """Project durable worker ownership into the in-memory workforce only."""
        with self._lock:
            worker = self.registry.get(durable_worker.name)
            if worker is None:
                worker = WorkerInfo(
                    name=durable_worker.name,
                    worker_type=durable_worker.worker_type,
                )
                self.registry.register(worker)

            worker.worker_type = durable_worker.worker_type
            worker.capabilities = list(durable_worker.capabilities or [])
            worker.status = WorkerStatus(durable_worker.status)
            worker.missions_completed = durable_worker.missions_completed
            worker.success_rate = durable_worker.success_rate
            worker.created_at = durable_worker.created_at
            worker.updated_at = durable_worker.updated_at
            worker.current_mission = (
                mission_name if worker.status is WorkerStatus.BUSY else None
            )
            return worker

    def get_worker(
        self,
        worker_name: str,
    ):
        with self._lock:
            return self.registry.get(worker_name)

    def online_workers(self):
        with self._lock:
            return [
                worker
                for worker in self.registry.all()
                if worker.status is WorkerStatus.ONLINE
            ]

    def busy_workers(self):
        with self._lock:
            return [
                worker
                for worker in self.registry.all()
                if worker.status is WorkerStatus.BUSY
            ]

    def offline_workers(self):
        with self._lock:
            return [
                worker
                for worker in self.registry.all()
                if worker.status is WorkerStatus.OFFLINE
            ]

    def summary(self):
        with self._lock:
            workers = self.registry.all()
            return {
                "total": len(workers),
                "online": len(
                    worker
                    for worker in workers
                    if worker.status is WorkerStatus.ONLINE
                ),
                "busy": len(
                    worker
                    for worker in workers
                    if worker.status is WorkerStatus.BUSY
                ),
                "offline": len(
                    worker
                    for worker in workers
                    if worker.status is WorkerStatus.OFFLINE
                ),
            }

    def clear(self):
        with self._lock:
            self.registry.clear()
