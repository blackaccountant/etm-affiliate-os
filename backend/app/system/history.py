"""
Execution History

Stores workflow execution history for
Mission Control.
"""

from datetime import datetime


class ExecutionHistory:

    def __init__(self):

        self._history = []


    def add(self, execution: dict):

        execution = execution.copy()

        execution["timestamp"] = datetime.now().isoformat()

        self._history.append(execution)


    def all(self):

        return self._history


    def latest(self):

        if not self._history:

            return None

        return self._history[-1]


    def clear(self):

        self._history.clear()


    def update_status(
        self,
        workflow: str,
        status: str,
    ):

        for item in reversed(self._history):

            if item["workflow"] == workflow:

                item["status"] = status

                return item

        return None