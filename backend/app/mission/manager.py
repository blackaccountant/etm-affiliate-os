"""
Mission Manager

Coordinates complete mission execution.
"""

from app.mission.mission import Mission
from app.mission.registry import MissionRegistry
from app.mission.mission_result import MissionResult
from app.mission.result_registry import ResultRegistry

from app.scheduler.scheduler import Scheduler
from app.executor.executor import TaskExecutor


class MissionManager:

    def __init__(self):

        self.registry = MissionRegistry()

        self.results = ResultRegistry()

        self.scheduler = Scheduler()

        self.executor = TaskExecutor()


    def create_mission(
        self,
        name,
        objective,
        workflow,
        metadata=None,
    ):

        mission = Mission(
            name=name,
            objective=objective,
            workflow=workflow,
            metadata=metadata,
        )

        self.registry.add(mission)

        return mission


    def execute(self, mission):

        task = self.scheduler.schedule(
            workflow_name=mission.workflow,
            payload=mission.metadata,
        )

        workflow_result = self.executor.execute(task)

        result = MissionResult(
            mission_id=mission.id,
            success=True,
            data=workflow_result,
        )

        self.results.add(result)

        return result


    def get_mission(
        self,
        mission_id,
    ):

        return self.registry.get(mission_id)


    def get_results(
        self,
        mission_id,
    ):

        return self.results.get_by_mission(
            mission_id
        )


    def missions(self):

        return self.registry.all()


    def clear(self):

        self.registry.clear()

        self.results.clear()