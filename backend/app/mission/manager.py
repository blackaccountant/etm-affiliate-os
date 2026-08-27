"""
Mission Manager

Coordinates mission execution and persists
complete execution history, including retry state.
"""

import json

from datetime import datetime, timezone

from app.mission.mission import Mission
from app.mission.registry import MissionRegistry
from app.mission.mission_result import MissionResult
from app.mission.result_registry import ResultRegistry

from app.scheduler.scheduler import Scheduler
from app.executor.executor import TaskExecutor

from app.workforce.manager import WorkforceManager

from app.database.session import SessionLocal
from app.models.execution import Execution

from app.retry.failure_classifier import FailureClassifier


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

        self.failure_classifier = (
            FailureClassifier()
        )


    # ==================================================
    # Create Mission
    # ==================================================

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


    # ==================================================
    # Execute Mission
    # ==================================================

    def execute(
        self,
        mission,
        worker=None,
    ):

        started_at = datetime.now(
            timezone.utc
        )


        # --------------------------------------------------
        # Create task
        # --------------------------------------------------

        task = self.scheduler.schedule(
            workflow_name=mission.workflow,
            payload=mission.metadata,
        )


        if worker:

            task.assign_worker(
                worker
            )


        # --------------------------------------------------
        # Execute workflow
        # --------------------------------------------------

        workflow_result = self.executor.execute(
            task
        )


        completed_at = datetime.now(
            timezone.utc
        )


        duration = (
            completed_at - started_at
        ).total_seconds()


        # --------------------------------------------------
        # Extract workflow result
        # --------------------------------------------------

        success = False

        workflow_errors = []


        if workflow_result is not None:

            success = getattr(
                workflow_result,
                "success",
                False,
            )


            workflow_errors = getattr(
                workflow_result,
                "errors",
                [],
            )


        if workflow_errors is None:

            workflow_errors = []


        # --------------------------------------------------
        # Determine error text
        # --------------------------------------------------

        error_text = None


        if not success:

            if workflow_errors:

                error_text = "; ".join(
                    str(error)
                    for error in workflow_errors
                )

            else:

                error_text = (
                    "Mission execution failed."
                )


        # --------------------------------------------------
        # Classify failure
        # --------------------------------------------------

        failure_info = {

            "failure_type": None,

            "retryable": False,

        }


        if not success:

            failure_info = (
                self.failure_classifier.classify(
                    error_text
                )
            )


        failure_type = (
            failure_info.get(
                "failure_type"
            )
        )


        retryable = (
            failure_info.get(
                "retryable",
                False,
            )
        )


        # --------------------------------------------------
        # Retry policy
        # --------------------------------------------------

        retry_policy = (
            self.executor.retry_policy
        )


        max_retries = getattr(
            retry_policy,
            "max_attempts",
            3,
        )


        task_retry_count = getattr(
            task,
            "retry_count",
            0,
        )


        task_is_queued = (
            getattr(
                task,
                "status",
                None,
            )
            == "QUEUED"
        )


        # --------------------------------------------------
        # Determine whether this execution is actually
        # scheduled for retry.
        # --------------------------------------------------

        retrying = (

            not success

            and retryable

            and task_is_queued

            and task_retry_count > 0

            and task_retry_count < max_retries

        )


        # Permanent failures must never become QUEUED
        # just because a task happens to have retry state.

        if not retryable:

            retrying = False


        retry_count = task_retry_count


        # --------------------------------------------------
        # Calculate next retry time
        #
        # IMPORTANT:
        # Only calculate this when an actual retry
        # has been scheduled.
        # --------------------------------------------------

        next_retry_at = None


        if retrying:

            next_retry_at = (
                retry_policy.calculate_next_retry(
                    task
                )
            )


        # --------------------------------------------------
        # Build workflow data
        # --------------------------------------------------

        if workflow_result is None:

            workflow_data = {

                "success": False,

                "status": (
                    "QUEUED"
                    if retrying
                    else "FAILED"
                ),

                "retry_count": retry_count,

                "error": error_text,

            }

        elif hasattr(
            workflow_result,
            "model_dump",
        ):

            workflow_data = (
                workflow_result.model_dump()
            )

        elif hasattr(
            workflow_result,
            "dict",
        ):

            workflow_data = (
                workflow_result.dict()
            )

        elif hasattr(
            workflow_result,
            "__dict__",
        ):

            workflow_data = (
                workflow_result.__dict__
            )

        else:

            workflow_data = str(
                workflow_result
            )


        # --------------------------------------------------
        # Mission result
        # --------------------------------------------------

        result = MissionResult(
            mission_id=mission.id,

            success=(
                success
                if not retrying
                else False
            ),

            data=workflow_result,
        )


        self.results.add(
            result
        )


        # --------------------------------------------------
        # Final execution status
        # --------------------------------------------------

        if success:

            final_status = "COMPLETED"

        elif retrying:

            final_status = "QUEUED"

        else:

            final_status = "FAILED"


        # --------------------------------------------------
        # Persistent result
        # --------------------------------------------------

        persistent_result = {

            "success": (
                success
                if not retrying
                else False
            ),

            "mission_id": mission.id,

            "mission_name": mission.name,

            "workflow": mission.workflow,

            "worker": (
                worker.name
                if worker
                else None
            ),

            "duration": duration,

            "retry_count": retry_count,

            "max_retries": max_retries,

            "status": final_status,

            "failure_type": failure_type,

            "retryable": retryable,

            "next_retry_at": (
                next_retry_at
                if retrying
                else None
            ),

            "errors": workflow_errors,

            "error": error_text,

            "result": workflow_data,

        }


        # --------------------------------------------------
        # Persist execution
        # --------------------------------------------------

        db = SessionLocal()


        try:

            execution = Execution(

                mission_id=mission.id,

                mission_name=mission.name,

                worker_name=(
                    worker.name
                    if worker
                    else None
                ),

                workflow_name=mission.workflow,

                status=final_status,

                result_data=json.dumps(
                    persistent_result,
                    default=str,
                ),

                input_data=json.dumps(
                    task.payload,
                    default=str,
                ),

                started_at=started_at,

                completed_at=(
                    None
                    if retrying
                    else completed_at
                ),

                duration=duration,

                retry_count=retry_count,

                max_retries=max_retries,

                next_retry_at=next_retry_at,

                failure_type=failure_type,

                error=error_text,

            )


            db.add(
                execution
            )

            db.commit()

            db.refresh(
                execution
            )


        finally:

            db.close()


        # --------------------------------------------------
        # Runtime memory
        # --------------------------------------------------

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

                    "success": (
                        success
                        if not retrying
                        else False
                    ),

                    "status": final_status,

                    "retry_count": retry_count,

                    "max_retries": max_retries,

                    "failure_type": failure_type,

                    "retryable": retryable,

                    "next_retry_at": (
                        next_retry_at
                        if retrying
                        else None
                    ),

                    "data": workflow_result,

                },
            )


        return result


    # ==================================================
    # Launch Mission
    # ==================================================

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


    # ==================================================
    # Mission Queries
    # ==================================================

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