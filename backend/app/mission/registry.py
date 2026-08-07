"""
Mission Registry

Stores and manages all missions
known to ETM Affiliate OS.
"""

from app.mission.mission import Mission


class MissionRegistry:

    def __init__(self):

        self._missions = {}


    def add(
        self,
        mission: Mission,
    ):

        self._missions[mission.id] = mission

        return mission


    def get(
        self,
        mission_id: str,
    ):

        return self._missions.get(
            mission_id
        )


    def all(self):

        return list(
            self._missions.values()
        )


    def remove(
        self,
        mission_id: str,
    ):

        self._missions.pop(
            mission_id,
            None,
        )


    def clear(self):

        self._missions.clear()