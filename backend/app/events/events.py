"""
Event definitions for ETM Affiliate OS.
"""


class Event:

    def __init__(
        self,
        name: str,
        data: dict | None = None,
    ):

        self.name = name

        self.data = data or {}