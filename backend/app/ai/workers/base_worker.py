"""
Base AI Worker

Every AI worker in ETM Affiliate OS should inherit from this class.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from app.ai.workers.result import WorkerResult
from app.ai.workers.task import WorkerTask


class BaseWorker(ABC):
    """
    Base class for all AI workers.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, task: WorkerTask) -> WorkerResult:
        """
        Execute a worker task.

        Every worker must implement this method.
        """
        raise NotImplementedError

    def execute(self, task: WorkerTask) -> WorkerResult:
        """
        Standard execution pipeline for all workers.
        """

        start = time.perf_counter()

        try:
            result = self.run(task)

            result.execution_time = (
                time.perf_counter() - start
            )

            result.worker_name = self.name

            return result

        except Exception as exc:

            return WorkerResult(
                success=False,
                worker_name=self.name,
                action=task.action,
                message="Worker execution failed.",
                execution_time=time.perf_counter() - start,
                error=str(exc),
            )

    def __str__(self) -> str:
        return self.name