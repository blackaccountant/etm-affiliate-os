"""
Mission Result Registry

Stores mission results for
ETM Affiliate OS.
"""


from app.mission.mission_result import MissionResult



class ResultRegistry:


    def __init__(self):

        self._results = {}



    def add(
        self,
        result: MissionResult,
    ):

        self._results[result.id] = result

        return result



    def get(
        self,
        result_id: str,
    ):

        return self._results.get(
            result_id
        )



    def get_by_mission(
        self,
        mission_id: str,
    ):

        return [

            result

            for result in self._results.values()

            if result.mission_id == mission_id

        ]



    def all(self):

        return list(
            self._results.values()
        )



    def clear(self):

        self._results.clear()