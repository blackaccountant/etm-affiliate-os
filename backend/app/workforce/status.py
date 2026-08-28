"""Worker availability status definitions."""

from enum import Enum


class WorkerStatus(str, Enum):
    """A worker is either unavailable, available, or assigned."""

    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    BUSY = "BUSY"
