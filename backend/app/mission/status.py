"""Mission lifecycle status definitions and transition validation."""

from enum import Enum


class MissionStatus(str, Enum):
    """Lifecycle states owned by the mission domain."""

    CREATED = "CREATED"
    WAITING_FOR_WORKER = "WAITING_FOR_WORKER"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


MISSION_STATUS_TRANSITIONS = {
    MissionStatus.CREATED: {
        MissionStatus.WAITING_FOR_WORKER,
        MissionStatus.ASSIGNED,
    },
    MissionStatus.WAITING_FOR_WORKER: {MissionStatus.ASSIGNED},
    MissionStatus.ASSIGNED: {MissionStatus.RUNNING},
    MissionStatus.RUNNING: {
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.RETRY_WAIT,
    },
    MissionStatus.RETRY_WAIT: {
        MissionStatus.RUNNING,
        MissionStatus.FAILED,
    },
    MissionStatus.COMPLETED: set(),
    MissionStatus.FAILED: set(),
}


def validate_mission_transition(
    current: MissionStatus,
    target: MissionStatus,
) -> None:
    """Reject transitions outside the mission lifecycle contract."""

    if target not in MISSION_STATUS_TRANSITIONS[current]:
        raise ValueError(
            "Invalid mission status transition: "
            f"{current.value} -> {target.value}"
        )
