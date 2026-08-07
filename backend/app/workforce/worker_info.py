"""
Worker Information

Represents an AI worker registered in
ETM Affiliate OS.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WorkerInfo:

    name: str

    worker_type: str

    status: str = "OFFLINE"

    current_mission: str | None = None

    missions_completed: int = 0

    success_rate: float = 100.0

    created_at: datetime = field(
        default_factory=datetime.now
    )


    def start_mission(
        self,
        mission_name: str,
    ):

        self.status = "BUSY"

        self.current_mission = mission_name


    def finish_mission(
        self,
        success: bool = True,
    ):

        self.status = "ONLINE"

        self.current_mission = None

        self.missions_completed += 1

        if not success:

            self.success_rate *= 0.95


    def to_dict(self):

        return {

            "name": self.name,

            "worker_type": self.worker_type,

            "status": self.status,

            "current_mission": self.current_mission,

            "missions_completed": self.missions_completed,

            "success_rate": self.success_rate,

            "created_at":
                self.created_at.isoformat(),

        }