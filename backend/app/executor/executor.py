"""
Task Executor

Executes workflows and manages task lifecycle,
including retry handling, failure recovery,
persisted execution state synchronization,
and retry backoff scheduling.
"""

from dataclasses import asdict, is_dataclass
from time import perf_counter
import json

from app.workflow_engine.workflow_engine import WorkflowEngine
from app.memory.memory_bus import MemoryBus
from app.retry.retry_policy import RetryPolicy
from app.retry.failure_classifier import FailureClassifier
from app.services.execution_service import ExecutionService


class TaskExecutor:

    def __init__(
        self,
        runtime=None,
        execution_service: ExecutionService | None = None,
    ):

        self.engine = WorkflowEngine()

        self.memory = MemoryBus()

        self.runtime = runtime

        self.execution_service = execution_service

        self.workforce = None

        self.retry_policy = RetryPolicy()

        self.failure_classifier = FailureClassifier()


        if runtime:

            self.workforce = getattr(
                runtime,
                "workforce",
                None,
            )


    # ==================================================
    # Worker Completion
    # ==================================================

    def update_worker_status(
        self,
        worker_name,
        success=True,
    ):

        if not self.workforce:

            return


        if not worker_name:

            return


        self.workforce.release(
            worker_name,
            success=success,
        )


    # ==================================================
    # Persisted Execution
    # ==================================================

    def _get_persisted_execution(
        self,
        task,
    ):

        if not self.execution_service:

            return None


        payload = getattr(
            task,
            "payload",
            None,
        )


        if not isinstance(
            payload,
            dict,
        ):

            return None


        execution_id = payload.get(
            "execution_id"
        )


        if not execution_id:

            return None


        return self.execution_service.get_by_id(
            execution_id
        )


    # ==================================================
    # Failure Type
    # ==================================================

    def _get_failure_type(
        self,
        task,
    ):

        payload = getattr(
            task,
            "payload",
            None,
        )


        if not isinstance(
            payload,
            dict,
        ):

            return None


        return payload.get(
            "failure_type"
        )


    # ==================================================
    # Serialize Workflow Result
    # ==================================================

    def _serialize_result(
        self,
        result,
    ):

        if is_dataclass(
            result
        ):

            return json.dumps(
                asdict(result),
                default=str,
            )


        if hasattr(
            result,
            "model_dump",
        ):

            return json.dumps(
                result.model_dump(),
                default=str,
            )


        if hasattr(
            result,
            "dict",
        ):

            return json.dumps(
                result.dict(),
                default=str,
            )


        if isinstance(
            result,
            dict,
        ):

            return json.dumps(
                result,
                default=str,
            )


        return json.dumps(
            {
                "result": str(
                    result
                )
            },
            default=str,
        )


    # ==================================================
    # Workflow Success
    # ==================================================

    def _workflow_succeeded(
        self,
        result,
    ):

        success = getattr(
            result,
            "success",
            None,
        )


        if success is None and isinstance(
            result,
            dict,
        ):

            success = result.get(
                "success"
            )


        # ------------------------------------------------
        # Backward compatibility:
        #
        # Workflows that don't expose a success field are
        # considered successful if they returned normally.
        # ------------------------------------------------

        if success is None:

            return True


        return bool(
            success
        )


    # ==================================================
    # Workflow Errors
    # ==================================================

    def _workflow_error_text(
        self,
        result,
        workflow_name,
    ):

        errors = getattr(
            result,
            "errors",
            None,
        )


        if errors is None and isinstance(
            result,
            dict,
        ):

            errors = result.get(
                "errors",
                [],
            )


        if errors is None:

            errors = []


        if errors:

            return "; ".join(
                str(error)
                for error in errors
            )


        return (
            f"Workflow '{workflow_name}' "
            "reported failure."
        )


    # ==================================================
    # Execute
    # ==================================================

    def execute(
        self,
        task,
    ):

        start = perf_counter()


        workflow_name = (
            task.workflow_name
        )


        worker_name = None


        if getattr(
            task,
            "worker",
            None,
        ):

            worker_name = (

                task.worker.name

                if hasattr(
                    task.worker,
                    "name",
                )

                else str(
                    task.worker
                )

            )


        # --------------------------------------------------
        # Resolve persisted execution for retry tasks.
        #
        # Ordinary tasks may not contain execution_id.
        # --------------------------------------------------

        persisted_execution = (
            self._get_persisted_execution(
                task
            )
        )


        # --------------------------------------------------
        # Runtime execution history
        # --------------------------------------------------

        if self.runtime:

            self.runtime.record_execution(
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "CREATED",
                    "duration": 0.0,
                }
            )


        try:

            # ==============================================
            # RUNNING
            # ==============================================

            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "RUNNING",
                )


                self.runtime.record_event(
                    f"{workflow_name} Started",
                    event_type="RUNNING",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                    },
                )


            # ==============================================
            # EXECUTE WORKFLOW
            # ==============================================

            result = self.engine.run(
                workflow_name=workflow_name,
                payload=task.payload,
            )


            duration = (
                perf_counter()
                - start
            )


            # ==============================================
            # SERIALIZE RESULT
            # ==============================================

            result_data = (
                self._serialize_result(
                    result
                )
            )


            # ==============================================
            # DETERMINE WORKFLOW SUCCESS
            # ==============================================

            workflow_success = (
                self._workflow_succeeded(
                    result
                )
            )


            # ==============================================
            # WORKFLOW SUCCESS
            # ==============================================

            if workflow_success:

                # ------------------------------------------
                # TASK COMPLETED
                # ------------------------------------------

                task.mark_completed()


                # ------------------------------------------
                # PERSIST COMPLETION
                # ------------------------------------------

                if persisted_execution:

                    self.execution_service.complete(
                        execution=(
                            persisted_execution
                        ),
                        duration=duration,
                        result_data=result_data,
                    )


                # ------------------------------------------
                # RUNTIME COMPLETION
                # ------------------------------------------

                if self.runtime:

                    self.runtime.update_execution_status(
                        workflow_name,
                        "COMPLETED",
                    )


                    self.runtime.record_event(
                        f"{workflow_name} Completed",
                        event_type="SUCCESS",
                        metadata={
                            "workflow": workflow_name,
                            "worker": worker_name,
                            "duration": duration,
                        },
                    )


                # ------------------------------------------
                # WORKER SUCCESS
                # ------------------------------------------

                self.update_worker_status(
                    worker_name,
                    success=True,
                )


                # ------------------------------------------
                # MEMORY
                # ------------------------------------------

                self.memory.store(
                    "last_execution",
                    {
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "status": "COMPLETED",
                        "duration": duration,
                    },
                )


                return result


            # ==============================================
            # WORKFLOW-LEVEL FAILURE
            #
            # The workflow executed normally but explicitly
            # reported success=False.
            #
            # This is NOT a Python exception.
            # ==============================================

            error_text = (
                self._workflow_error_text(
                    result,
                    workflow_name,
                )
            )


            # ==============================================
            # CLASSIFY WORKFLOW FAILURE
            # ==============================================

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


            # ==============================================
            # WORKFLOW FAILURE RETRY
            # ==============================================

            if retryable:

                retrying = (
                    self.retry_policy.execute_retry(
                        task
                    )
                )


                if retrying:

                    next_retry_at = (
                        self.retry_policy
                        .calculate_next_retry(
                            task
                        )
                    )


                    # --------------------------------------
                    # Preserve workflow result on retry.
                    # --------------------------------------

                    if persisted_execution:

                        persisted_execution.result_data = (
                            result_data
                        )


                        self.execution_service.schedule_retry(

                            execution=(
                                persisted_execution
                            ),

                            retry_count=(
                                task.retry_count
                            ),

                            max_retries=(
                                task.max_retries
                            ),

                            next_retry_at=(
                                next_retry_at
                            ),

                            failure_type=(
                                failure_type
                            ),

                            error=(
                                error_text
                            ),

                        )


                    # --------------------------------------
                    # Runtime retry event
                    # --------------------------------------

                    if self.runtime:

                        self.runtime.record_event(
                            f"{workflow_name} Retry Scheduled",
                            event_type="RETRY",
                            metadata={
                                "workflow": workflow_name,
                                "worker": worker_name,
                                "retry_count": (
                                    task.retry_count
                                ),
                                "next_retry_at": (
                                    next_retry_at.isoformat()
                                    if next_retry_at
                                    else None
                                ),
                                "failure_type": (
                                    failure_type
                                ),
                                "error": (
                                    error_text
                                ),
                            },
                        )


                    # --------------------------------------
                    # Memory
                    # --------------------------------------

                    self.memory.store(
                        "last_execution",
                        {
                            "workflow": workflow_name,
                            "worker": worker_name,
                            "status": "RETRYING",
                            "retry_count": (
                                task.retry_count
                            ),
                            "next_retry_at": (
                                next_retry_at.isoformat()
                                if next_retry_at
                                else None
                            ),
                            "duration": duration,
                            "failure_type": (
                                failure_type
                            ),
                            "error": (
                                error_text
                            ),
                        },
                    )


                    # --------------------------------------
                    # Do NOT mark completed.
                    # The persisted execution remains
                    # eligible for the retry scanner.
                    # --------------------------------------

                    return result


            # ==============================================
            # WORKFLOW PERMANENT FAILURE
            #
            # This includes:
            #
            # 1. Non-retryable workflow failures.
            #
            # 2. Retryable workflow failures where the
            #    retry policy has exhausted all attempts.
            # ==============================================

            task.mark_failed()


            # ----------------------------------------------
            # Persist permanent failure.
            #
            # Store the workflow result before calling fail().
            # ExecutionRepository.fail() commits the object,
            # so result_data is persisted together with the
            # failure state.
            # ----------------------------------------------

            if persisted_execution:

                persisted_execution.result_data = (
                    result_data
                )


                self.execution_service.fail(

                    execution=(
                        persisted_execution
                    ),

                    error=(
                        error_text
                    ),

                    failure_type=(
                        failure_type
                    ),

                    duration=(
                        duration
                    ),

                    retry_count=(
                        task.retry_count
                    ),

                )


            # ----------------------------------------------
            # Runtime failure
            # ----------------------------------------------

            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "FAILED",
                )


                self.runtime.record_event(
                    f"{workflow_name} Failed",
                    event_type="ERROR",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "duration": duration,
                        "retry_count": (
                            task.retry_count
                        ),
                        "failure_type": (
                            failure_type
                        ),
                        "error": (
                            error_text
                        ),
                    },
                )


            # ----------------------------------------------
            # Worker failure
            # ----------------------------------------------

            self.update_worker_status(
                worker_name,
                success=False,
            )


            # ----------------------------------------------
            # Memory
            # ----------------------------------------------

            self.memory.store(
                "last_execution",
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "FAILED",
                    "duration": duration,
                    "retry_count": (
                        task.retry_count
                    ),
                    "failure_type": (
                        failure_type
                    ),
                    "error": (
                        error_text
                    ),
                },
            )


            return result


        except Exception as exc:

            duration = (
                perf_counter()
                - start
            )


            # ==============================================
            # RETRY POLICY
            # ==============================================

            retrying = (
                self.retry_policy.execute_retry(
                    task
                )
            )


            # ==============================================
            # Refresh persisted execution
            #
            # The retry policy changes the in-memory task
            # state. Re-resolve the DB execution before
            # persisting the new retry state.
            # ==============================================

            if persisted_execution:

                persisted_execution = (
                    self._get_persisted_execution(
                        task
                    )
                )


            # ==============================================
            # RETRY SCHEDULED
            # ==============================================

            if retrying:

                # ------------------------------------------
                # Calculate retry backoff
                #
                # RetryPolicy already calculates exponential
                # backoff based on the current retry count.
                #
                # Example with 30 second base:
                #
                # retry_count = 1 → 60 seconds
                # retry_count = 2 → 120 seconds
                #
                # The calculation is performed after
                # task.retry(), so the current retry count
                # represents the retry that was just consumed.
                # ------------------------------------------

                next_retry_at = (
                    self.retry_policy
                    .calculate_next_retry(
                        task
                    )
                )


                # ------------------------------------------
                # Persist retry state
                # ------------------------------------------

                if persisted_execution:

                    self.execution_service.schedule_retry(

                        execution=(
                            persisted_execution
                        ),

                        retry_count=(
                            task.retry_count
                        ),

                        max_retries=(
                            task.max_retries
                        ),

                        next_retry_at=(
                            next_retry_at
                        ),

                        failure_type=(
                            self._get_failure_type(
                                task
                            )
                        ),

                        error=str(
                            exc
                        ),

                    )


                # ------------------------------------------
                # Runtime event
                # ------------------------------------------

                if self.runtime:

                    self.runtime.record_event(
                        f"{workflow_name} Retry Scheduled",
                        event_type="RETRY",
                        metadata={
                            "workflow": workflow_name,
                            "worker": worker_name,
                            "retry_count": (
                                task.retry_count
                            ),
                            "next_retry_at": (
                                next_retry_at.isoformat()
                                if next_retry_at
                                else None
                            ),
                            "error": str(
                                exc
                            ),
                        },
                    )


                # ------------------------------------------
                # Memory
                # ------------------------------------------

                self.memory.store(
                    "last_execution",
                    {
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "status": "RETRYING",
                        "retry_count": (
                            task.retry_count
                        ),
                        "next_retry_at": (
                            next_retry_at.isoformat()
                            if next_retry_at
                            else None
                        ),
                        "duration": duration,
                        "error": str(
                            exc
                        ),
                    },
                )


                return None


            # ==============================================
            # PERMANENT FAILURE
            # ==============================================

            task.mark_failed()


            # ==============================================
            # PERSIST PERMANENT FAILURE
            # ==============================================

            if persisted_execution:

                self.execution_service.fail(

                    execution=(
                        persisted_execution
                    ),

                    error=str(
                        exc
                    ),

                    failure_type=(
                        self._get_failure_type(
                            task
                        )
                    ),

                    duration=duration,

                    retry_count=(
                        task.retry_count
                    ),

                )


            # ==============================================
            # RUNTIME FAILURE
            # ==============================================

            if self.runtime:

                self.runtime.update_execution_status(
                    workflow_name,
                    "FAILED",
                )


                self.runtime.record_event(
                    f"{workflow_name} Failed Permanently",
                    event_type="ERROR",
                    metadata={
                        "workflow": workflow_name,
                        "worker": worker_name,
                        "duration": duration,
                        "retry_count": (
                            task.retry_count
                        ),
                        "error": str(
                            exc
                        ),
                    },
                )


            # ==============================================
            # WORKER FAILURE
            # ==============================================

            self.update_worker_status(
                worker_name,
                success=False,
            )


            # ==============================================
            # MEMORY
            # ==============================================

            self.memory.store(
                "last_execution",
                {
                    "workflow": workflow_name,
                    "worker": worker_name,
                    "status": "FAILED",
                    "duration": duration,
                    "retry_count": (
                        task.retry_count
                    ),
                    "error": str(
                        exc
                    ),
                },
            )


            raise