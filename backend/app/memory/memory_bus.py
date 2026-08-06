"""
Memory Bus

Temporary in-memory storage shared by workers,
workflows and future autonomous agents.
"""


class MemoryBus:

    def __init__(self):
        self._memory = {}

    def store(self, key: str, value):
        self._memory[key] = value

    def get(self, key: str, default=None):
        return self._memory.get(key, default)

    def delete(self, key: str):
        if key in self._memory:
            del self._memory[key]

    def clear(self):
        self._memory.clear()

    def keys(self):
        return list(self._memory.keys())

    def exists(self, key: str):
        return key in self._memory