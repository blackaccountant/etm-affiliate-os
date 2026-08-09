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

from app.workforce.manager import WorkforceManager


class MissionManager:

    def __init__(
        self,
        workforce=None,
        runtime=None,
    ):

        self.registry = MissionRegistry()

        self.results = ResultRegistry()

        self.scheduler = Scheduler()

        self.runtime = runtime

        self.executor = TaskExecutor(
            runtime=runtime
        )

        self.workforce = (
            workforce
            if workforce is not None
            else WorkforceManager()
        )


    def create_mission(
        self,
        name,
        objective,
        workflow,
        metadata=None,
        required_capability=None,
    ):

        mission = Mission(
            name=name,
            objective=objective,
            workflow=workflow,
            metadata=metadata,
            required_capability=required_capability,
        )

        self.registry.add(
            mission
        )

        return mission


    def execute(
        self,
        mission,
        worker=None,
    ):

        task = self.scheduler.schedule(
            workflow_name=mission.workflow,
            payload=mission.metadata,
        )


        if worker:

            task.assign_worker(
                worker
            )


        workflow_result = self.executor.execute(
            task
        )


        # -----------------------------------------
        # Determine real execution status
        # -----------------------------------------

        success = True
        error = None


        if hasattr(
            workflow_result,
            "success",
        ):

            success = workflow_result.success


        if not success:

            error = getattr(
                workflow_result,
                "error",
                "Workflow execution failed.",
            )


        result = MissionResult(
            mission_id=mission.id,
            success=success,
            data=workflow_result,
            error=error,
        )


        self.results.add(
            result
        )


        if self.runtime:

            self.runtime.memory.store(
                "latest_mission_result",
                {
                    "mission_id": mission.id,
                    "mission": mission.name,
                    "workflow": mission.workflow,
                    "worker": (
                        worker.name
                        if worker
                        else None
                    ),
                    "success": result.success,
                    "data": workflow_result,
                    "error": result.error,
                },
            )


        return result



    def launch(
        self,
        name,
        objective,
        workflow,
        metadata=None,
        required_capability=None,
    ):


        mission = self.create_mission(
            name=name,
            objective=objective,
            workflow=workflow,
            metadata=metadata,
            required_capability=required_capability,
        )


        if mission.required_capability:

            worker = (
                self.workforce.assign_by_capability(
                    mission.name,
                    mission.required_capability,
                )
            )

        else:

            worker = (
                self.workforce.assign(
                    mission.name
                )
            )


        result = self.execute(
            mission,
            worker=worker,
        )


        return {

            "mission": mission,

            "worker": worker,

            "result": result,

        }



    def get_mission(
        self,
        mission_id,
    ):

        return self.registry.get(
            mission_id
        )


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