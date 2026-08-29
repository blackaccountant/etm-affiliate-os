"""Validate a claimed retry, then run it through the shared attempt runtime."""

from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.mission.status import MissionStatus, validate_mission_transition
from app.services.execution_attempt_runner import ExecutionAttemptRunner
from app.services.execution_lease import ExecutionLeaseAuthority


class RetryLifecycleCoordinator:
    """Keep frozen retry claim validation separate from active finalization."""

    def __init__(self, db, execution_service, mission_repository, worker_repository,
                 workforce, executor, runtime=None, session_factory=None):
        self.db = db
        self.execution_service = execution_service
        self.missions = mission_repository
        self.workers = worker_repository
        self.workforce = workforce
        self.executor = executor
        self.runtime = runtime
        self.session_factory = session_factory or sessionmaker(
            bind=db.get_bind(), autoflush=False, autocommit=False,
        )

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

    def _ownership_error(self, execution, message):
        """Handle a malformed scanner claim before any active attempt starts."""
        self.execution_service.fail(
            execution, error=message, failure_type="OWNERSHIP_RECOVERY",
            retry_count=execution.retry_count,
        )
        self._event("Retry ownership recovery failure", execution_id=execution.id, error=message)
        return None

    def _restore_recoverable(self, execution, mission, worker_name, error):
        """Undo preparation failure before lease acquisition without spending retry budget."""
        if execution is not None and execution.status == "RETRYING":
            self.execution_service.schedule_retry(
                execution, retry_count=execution.retry_count,
                max_retries=execution.max_retries, next_retry_at=datetime.now(timezone.utc),
                failure_type=execution.failure_type, error=error,
            )
        if mission is not None and mission.status == MissionStatus.RUNNING.value:
            self._transition(
                mission, MissionStatus.RETRY_WAIT,
                result_data=getattr(execution, "result_data", None), last_error=error,
                current_worker_name=worker_name,
            )

    def execute(self, task):
        payload = getattr(task, "payload", {})
        execution_id = payload.get("execution_id") if isinstance(payload, dict) else None
        payload_mission_id = payload.get("mission_id") if isinstance(payload, dict) else None
        payload_worker_name = payload.get("worker_name") if isinstance(payload, dict) else None
        execution = self._reload_execution(execution_id) if execution_id else None
        if execution is None:
            self._event("Retry ownership recovery failure", error="Execution is missing", execution_id=execution_id)
            return None
        if execution.status != "RETRYING":
            return self._ownership_error(execution, "Claimed retry execution is not RETRYING")
        authority = getattr(task, "execution_authority", None)
        if authority is None and execution.lease_owner is not None:
            authority = ExecutionLeaseAuthority(
                execution.id, execution.lease_owner, execution.lease_generation,
            )
        if authority is not None and (
            authority.execution_id != execution.id
            or authority.lease_owner != execution.lease_owner
            or authority.lease_generation != execution.lease_generation
        ):
            return self._ownership_error(execution, "Retry lease authority does not match durable execution")
        if not execution.mission_id or payload_mission_id != execution.mission_id:
            return self._ownership_error(execution, "Retry mission identity does not match durable execution")
        if not execution.worker_name or payload_worker_name != execution.worker_name:
            return self._ownership_error(execution, "Retry worker identity does not match durable execution")

        mission = self.missions.get_by_id(execution.mission_id)
        if mission is None:
            return self._ownership_error(execution, "Retry mission record is missing")
        leased_claim = authority is not None
        expected_mission_status = MissionStatus.RUNNING.value if leased_claim else MissionStatus.RETRY_WAIT.value
        if mission.status != expected_mission_status:
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
            task.assign_worker(worker_info)
        except Exception as exc:
            self._restore_recoverable(execution, mission, durable_worker.name, str(exc))
            self._event("Retry lifecycle preparation failed", execution_id=execution.id, error=str(exc))
            raise

        attempt = ExecutionAttemptRunner(
            self.session_factory, self.executor, workforce=self.workforce,
        ).execute(
            execution_id=execution.id, mission_id=mission.id, mission_name=mission.name,
            worker_name=durable_worker.name, task=task,
            before_workflow=None if leased_claim else lambda: self._transition(
                mission, MissionStatus.RUNNING, current_worker_name=durable_worker.name,
            ),
            authority=authority,
        )
        if attempt.ownership_lost:
            self._event("Execution lease ownership was lost", execution_id=execution.id)
            return None
        if attempt.error is not None:
            raise attempt.error
        return attempt.result
