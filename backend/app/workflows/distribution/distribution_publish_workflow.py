"""Initial publication of one immutable DistributionRun payload."""

from datetime import datetime, timezone

from app.database.session import SessionLocal
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import (
    DistributionFailureCategory,
    DistributionPublishRequest,
    DistributionRunStatus,
    DistributionValidationRequest,
    payload_fingerprint_for_body,
)
from app.distribution.exceptions import UnsupportedDistributionPlatformError
from app.distribution.failure_adapter import DistributionFailureAdapter
from app.distribution.mission_contracts import DistributionWorkflowPayload
from app.models.content_evaluation import ContentEvaluation
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.execution_runtime_context import current_execution_runtime_context
from app.workflow_engine.workflow_result import WorkflowResult


class DistributionPublishWorkflow:
    workflow_name = "distribution_publish"

    def __init__(self, session_factory=SessionLocal, adapter_registry=None):
        self.session_factory = session_factory
        self.adapter_registry = adapter_registry or DistributionAdapterRegistry()

    def _failure(self, values, message):
        return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=[message])

    @staticmethod
    def _owned_set(repository, run, context, status, *, category=None, error=None, result=None):
        values = {"failure_category": category, "error_summary": error}
        if status == "PUBLISHING":
            values["publishing_started_at"] = datetime.now(timezone.utc)
        if status == "COMPLETED":
            values.update(
                completed_at=datetime.now(timezone.utc),
                external_post_id=result.external_post_id,
                external_url=result.external_url,
                result_metadata=result.safe_metadata,
                failure_category=None,
                error_summary=None,
            )
        transitioned = repository.transition_owned(
            run.id,
            context.authority,
            expected_statuses=(run.status,),
            status=status,
            values=values,
        )
        if transitioned is None:
            raise RuntimeError("distribution run state changed before the active attempt could continue")
        return transitioned

    @staticmethod
    def _trusted_retry(db, payload, run):
        required = {"execution_id", "mission_id", "worker_name", "retry_count", "max_retries"}
        if not isinstance(payload, dict) or not required.issubset(payload):
            return False
        execution = db.get(Execution, payload["execution_id"])
        mission = db.get(MissionRecord, payload["mission_id"])
        worker = db.get(Worker, payload["worker_name"])
        if not execution or not mission or not worker:
            return False
        if execution.status != "RETRYING" or mission.status != "RUNNING" or worker.status != "BUSY":
            return False
        if execution.mission_id != mission.id or execution.worker_name != worker.name or worker.current_mission_id != mission.id:
            return False
        import json
        try:
            stored = json.loads(execution.input_data or "{}")
        except (TypeError, ValueError):
            return False
        return stored.get("distribution_run_id") == run.id

    def execute(self, payload):
        try:
            values = DistributionWorkflowPayload.from_payload(payload)
        except ValueError as error:
            return WorkflowResult(False, self.workflow_name, {}, errors=[f"validation error: {error}"])

        db = self.session_factory()
        try:
            run = db.get(DistributionRun, values.distribution_run_id)
            if run is None:
                return self._failure(values, "validation error: distribution run does not exist")

            context = current_execution_runtime_context()
            if run.status == DistributionRunStatus.PUBLISHING.value:
                if context is None or not context.is_recovery:
                    return self._failure(values, "validation error: distribution run is already publishing")
                repository = DistributionRunRepository(db)
                transitioned = repository.transition_owned(
                    run.id,
                    context.authority,
                    expected_statuses=(DistributionRunStatus.PUBLISHING.value,),
                    status=DistributionRunStatus.RECONCILIATION_REQUIRED.value,
                    values={
                        "failure_category": DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT.value,
                        "error_summary": "external publish result requires reconciliation",
                    },
                )
                if transitioned is None:
                    return self._failure(values, "validation error: distribution run publishing state changed")
                return WorkflowResult(
                    True,
                    self.workflow_name,
                    {
                        "distribution_run_id": transitioned.id,
                        "reconciliation_required": True,
                        "safe_message": "external publish result requires reconciliation",
                    },
                    errors=[],
                )

            if context is None:
                return self._failure(values, "execution runtime authority is required")
            repository = DistributionRunRepository(db)
            retry = self._trusted_retry(db, payload, run)
            if run.status == DistributionRunStatus.RETRY_WAIT.value:
                if not retry:
                    return self._failure(values, "validation error: distribution retry is not coordinator-owned")
                run = self._owned_set(repository, run, context, "RUNNING")
            elif run.status != DistributionRunStatus.CREATED.value:
                return self._failure(values, "validation error: distribution run is not executable")

            artifact = db.get(GeneratedContentArtifact, run.generated_content_artifact_id)
            evaluation = db.get(ContentEvaluation, run.content_evaluation_id)
            if (
                artifact is None
                or evaluation is None
                or evaluation.artifact_id != artifact.id
                or evaluation.generation_run_id != artifact.generation_run_id
                or evaluation.decision != "APPROVED"
                or evaluation.approved is not True
            ):
                self._owned_set(repository, run, context, "FAILED", category=DistributionFailureCategory.UNKNOWN_PERMANENT.value, error="validation error: distribution lineage is not eligible")
                return self._failure(values, "validation error: distribution lineage is not eligible")

            try:
                integrity = payload_fingerprint_for_body(run.prepared_content_body) == run.payload_fingerprint
            except ValueError:
                integrity = False
            if not integrity:
                self._owned_set(repository, run, context, "FAILED", category=DistributionFailureCategory.UNKNOWN_PERMANENT.value, error="validation error: distribution payload integrity check failed")
                return self._failure(values, "validation error: distribution payload integrity check failed")

            try:
                adapter = self.adapter_registry.resolve(run.platform)
            except UnsupportedDistributionPlatformError:
                self._owned_set(repository, run, context, "FAILED", category=DistributionFailureCategory.UNSUPPORTED_PLATFORM.value, error="unsupported distribution platform")
                return self._failure(values, "unsupported distribution platform")

            validated = adapter.validate_target(DistributionValidationRequest(run.id, run.platform, run.account_reference, run.destination, payload_fingerprint=run.payload_fingerprint))
            if not validated.valid:
                category = validated.failure_category or DistributionFailureCategory.INVALID_DESTINATION
                message = DistributionFailureAdapter.to_classifier_text(category)
                self._owned_set(repository, run, context, "FAILED", category=category.value, error=message)
                return self._failure(values, message)

            if run.status != "RUNNING":
                run = self._owned_set(repository, run, context, "RUNNING")
            run = self._owned_set(repository, run, context, "PUBLISHING")
            try:
                result = adapter.publish(DistributionPublishRequest(run.id, artifact.id, evaluation.id, run.platform, run.account_reference, run.destination, run.payload_fingerprint, run.prepared_content_body, run.scheduled_for))
            except Exception:
                self._owned_set(repository, run, context, "FAILED", category=DistributionFailureCategory.UNKNOWN_PERMANENT.value, error="permanent distribution provider error")
                return self._failure(values, "permanent distribution provider error")

            if result.success:
                self._owned_set(repository, run, context, "COMPLETED", result=result)
                return WorkflowResult(True, self.workflow_name, {"distribution_run_id": run.id, "generated_content_artifact_id": artifact.id, "content_evaluation_id": evaluation.id, "platform": run.platform, "destination": run.destination, "external_post_id": result.external_post_id, "external_url": result.external_url, "published_at": result.published_at.isoformat()}, errors=[])

            category = result.failure_category or DistributionFailureCategory.UNKNOWN_PERMANENT
            message = DistributionFailureAdapter.to_classifier_text(category)
            status = "RECONCILIATION_REQUIRED" if category is DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT else "RETRY_WAIT" if category.retryable else "FAILED"
            self._owned_set(repository, run, context, status, category=category.value, error=message)
            return self._failure(values, message)
        finally:
            db.close()
