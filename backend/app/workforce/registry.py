"""
Workforce Registry

Stores all AI workers known to
ETM Affiliate OS.
"""

from app.workforce.worker_info import WorkerInfo


class WorkforceRegistry:

    def __init__(self):

        self._workers = {}


    def register(
        self,
        worker: WorkerInfo,
    ):

        if worker.name in self._workers:

            raise ValueError(
                f"Worker already registered: {worker.name}"
            )

        self._workers[worker.name] = worker

        return worker


    def get(
        self,
        name: str,
    ):

        return self._workers.get(name)


    def all(self):

        return list(
            self._workers.values()
        )


    def remove(
        self,
        name: str,
    ):

        self._workers.pop(
            name,
            None,
        )


    def clear(self):

        self._workers.clear()
