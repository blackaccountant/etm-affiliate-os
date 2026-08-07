"""
Mission Result

Stores the output of a completed mission.
"""


from datetime import datetime


from uuid import uuid4



class MissionResult:


    def __init__(
        self,
        mission_id: str,
        success: bool,
        data: dict | None = None,
        error: str | None = None,
    ):


        self.id = str(uuid4())

        self.mission_id = mission_id

        self.success = success

        self.data = data or {}

        self.error = error

        self.created_at = datetime.now()



    def to_dict(self):

        return {

            "id": self.id,

            "mission_id": self.mission_id,

            "success": self.success,

            "data": self.data,

            "error": self.error,

            "created_at":
                self.created_at.isoformat(),

        }