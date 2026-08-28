"""Durable Mission/Worker lifecycle coordination for recovered retry tasks."""

from datetime import datetime, timezone

from app.mission.status import MissionStatus, validate_mission_transition


class RetryLifecycleCoordinator:
    """Execute an already-claimed retry while preserving durable ownership."""

    def __init__(
        self,
        db,
        execution_service,
        mission_repository,
        worker_repository,
        workforce,
        executor,
        runtime=None,
    ):
        self.db = db
        self.execution_service = execution_service
        self.missions = mission_repository
        self.workers = worker_repository
        self.workforce = workforce
        self.executor = executor
        self.runtime = runtime

    def _event(self, message, **metadata):
        if not self.runtime:
            return
        try:
            self.runtime.record_event(message, event_type="ERROR", metadata=metadata)
        except Exception:
            pass

    def _reload_execution(self, execution_id):
        self.db.expire_all()
        return self.execution_service.get_by_id(execution_id)

    def _transition(self, mission, status, **kwargs):
        target = MissionStatus(status)
        validate_mission_transition(MissionStatus(mission.status), target)
        record = self.missions.update_status(mission.id, target, **kwargs)
        if record is None:
            raise RuntimeError(f"Durable mission {mission.id} disappeared during retry recovery")
        return record

    @staticmethod
    def _result_data(execution):
        return getattr(execution, "result_data", None)

    def _ownership_error(self, execution, message):
        self.execution_service.fail(
            execution,
            error=message,
            failure_type="OWNERSHIP_RECOVERY",
            retry_count=execution.retry_count,
        )
        self._event("Retry ownership recovery failure", execution_id=execution.id, error=message)
        return None

    def _restore_recoverable(self, execution, mission, worker_name, error):
        """Return a claimed retry to its durable waiting state without consuming retry budget."""
        if execution is not None and execution.status == "RETRYING":
            self.execution_service.schedule_retry(
                execution=execution,
                retry_count=execution.retry_count,
                max_retries=execution.max_retries,
                next_retry_at=datetime.now(timezone.utc),
                failure_type=execution.failure_type,
                error=error,
            )
        if mission is not None and mission.status == MissionStatus.RUNNING.value:
            self._transition(
                mission,
                MissionStatus.RETRY_WAIT,
                result_data=self._result_data(execution),
                last_error=error,
                current_worker_name=worker_name,
            )

    def _finalize(self, execution, mission, durable_worker, worker_info, original_error):
        status = execution.status
        if status == "COMPLETED":
            self._transition(
                mission,
                MissionStatus.COMPLETED,
                result_data=self._result_data(execution),
                last_error=None,
                current_worker_name=None,
            )
            released = self.workers.release(durable_worker.name, mission.id, success=True)
            if not released:
                message = f"Durable worker release failed for worker {durable_worker.name} and mission {mission.id}"
                self._event(message, execution_id=execution.id)
                raise RuntimeError(message)
            worker_info = self.workforce.sync_from_durable(
                self.workers.get_by_name(durable_worker.name), mission.name
            )
            return worker_info

        if status == "QUEUED":
            self._transition(
                mission,
                MissionStatus.RETRY_WAIT,
                result_data=self._result_data(execution),
                last_error=execution.error,
                current_worker_name=durable_worker.name,
            )
            return self.workforce.sync_from_durable(durable_worker, mission.name)

        if status == "FAILED":
            self._transition(
                mission,
                MissionStatus.FAILED,
                result_data=self._result_data(execution),
                last_error=execution.error,
                current_worker_name=None,
            )
            released = self.workers.release(durable_worker.name, mission.id, success=False)
            if not released:
                message = f"Durable worker release failed for worker {durable_worker.name} and mission {mission.id}"
                self._event(message, execution_id=execution.id)
                raise RuntimeError(message)
            worker_info = self.workforce.sync_from_durable(
                self.workers.get_by_name(durable_worker.name), mission.name
            )
            if original_error is not None:
                raise original_error
            return worker_info

        message = f"Unexpected retry execution status {status} for execution {execution.id}"
        self._restore_recoverable(execution, mission, durable_worker.name, message)
        self._event(message, execution_id=execution.id)
        if original_error is not None:
            raise original_error
        return None

    def execute(self, task):
        payload = getattr(task, "payload", {})
        execution_id = payload.get("execution_id") if isinstance(payload, dict) else None
        payload_mission_id = payload.get("mission_id") if isinstance(payload, dict) else None
        payload_worker_name = payload.get("worker_name") if isinstance(payload, dict) else None
        execution = self._reload_execution(execution_id) if execution_id else None
        mission = None

        if execution is None:
            self._event("Retry ownership recovery failure", error="Execution is missing", execution_id=execution_id)
            return None

        if execution.status != "RETRYING":
            return self._ownership_error(execution, "Claimed retry execution is not RETRYING")
        if not execution.mission_id or payload_mission_id != execution.mission_id:
            return self._ownership_error(execution, "Retry mission identity does not match durable execution")
        if not execution.worker_name or payload_worker_name != execution.worker_name:
            return self._ownership_error(execution, "Retry worker identity does not match durable execution")

        mission = self.missions.get_by_id(execution.mission_id)
        if mission is None:
            return self._ownership_error(execution, "Retry mission record is missing")
        if mission.status != MissionStatus.RETRY_WAIT.value:
            return self._ownership_error(execution, "Retry mission is not in RETRY_WAIT")
        if mission.current_worker_name != execution.worker_name:
            return self._ownership_error(execution, "Retry mission worker ownership does not match execution")

        durable_worker = self.workers.get_by_name(execution.worker_name)
        if durable_worker is None:
            return self._ownership_error(execution, "Retry durable worker is missing")
        if durable_worker.status != "BUSY" or durable_worker.current_mission_id != mission.id:
            return self._ownership_error(execution, "Retry durable worker ownership does not match mission")

        try:
            worker_info = self.workforce.sync_from_durable(durable_worker, mission.name)
            self._transition(mission, MissionStatus.RUNNING, current_worker_name=durable_worker.name)
            task.assign_worker(worker_info)
        except Exception as exc:
            self._restore_recoverable(execution, mission, durable_worker.name, str(exc))
            self._event("Retry lifecycle preparation failed", execution_id=execution.id, error=str(exc))
            raise

        result = None
        original_error = None
        try:
            result = self.executor.execute(task)
        except Exception as exc:
            original_error = exc

        execution = self._reload_execution(execution.id)
        try:
            self._finalize(execution, mission, durable_worker, worker_info, original_error)
        except Exception:
            raise
        return result
