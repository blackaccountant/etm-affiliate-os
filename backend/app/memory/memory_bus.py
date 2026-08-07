"""
Memory Bus

Shared runtime memory for ETM Affiliate OS.
"""


class MemoryBus:

    def __init__(self):

        self._memory = {}

    # -------------------------
    # Store
    # -------------------------

    def store(self, key: str, value):

        self._memory[key] = value

    # -------------------------
    # Retrieve (legacy)
    # -------------------------

    def get(self, key: str, default=None):

        return self._memory.get(key, default)

    # -------------------------
    # Retrieve (new API)
    # -------------------------

    def retrieve(self, key: str, default=None):

        return self.get(key, default)

    # -------------------------
    # Exists
    # -------------------------

    def exists(self, key: str):

        return key in self._memory

    # -------------------------
    # Delete
    # -------------------------

    def delete(self, key: str):

        if key in self._memory:
            del self._memory[key]
            return True

        return False

    # -------------------------
    # Return all memory
    # -------------------------

    def all(self):

        return self._memory.copy()

    # -------------------------
    # Clear memory
    # -------------------------

    def clear(self):

        self._memory.clear()