"""
Execution History

Stores execution history for
Mission Control.
"""


class ExecutionHistory:

    def __init__(self):

        self._history = []


    def add(self, execution: dict):

        self._history.append(
            execution
        )


    def all(self):

        return list(
            self._history
        )


    def latest(self):

        if not self._history:

            return None

        return self._history[-1]


    def count(self):

        return len(
            self._history
        )


    def clear(self):

        self._history.clear()