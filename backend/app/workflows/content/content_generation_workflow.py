"""Mission workflow for one durable content-generation run."""

from app.database.session import SessionLocal
from app.content_intelligence.content_mission_contracts import ContentGenerationWorkflowPayload, ContentGenerationWorkflowResult
from app.content_intelligence.content_provider_failure_adapter import ContentProviderFailureAdapter
from app.content_intelligence.content_evaluator import ContentEvaluator
from app.content_intelligence.generation_contracts import ContentGenerationRequest, GenerationParameters
from app.content_intelligence.generation_service import ContentGenerationService
from app.models.content_generation_run import ContentGenerationRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.retry.retry_policy import RetryPolicy
from app.task_queue.task import Task
from app.workflow_engine.workflow_result import WorkflowResult


class ContentGenerationWorkflow:
    workflow_name = "content_generate"

    def __init__(self, session_factory=SessionLocal, generation_service_factory=ContentGenerationService, evaluator_factory=ContentEvaluator):
        self.session_factory = session_factory
        self.generation_service_factory = generation_service_factory
        self.evaluator_factory = evaluator_factory

    @staticmethod
    def _parameters(run):
        values = run.generation_parameters if isinstance(run.generation_parameters, dict) else {}
        return GenerationParameters(
            temperature=values.get("temperature", GenerationParameters().temperature),
            max_output_tokens=values.get("max_output_tokens", GenerationParameters().max_output_tokens),
        )

    def _failure(self, values, error):
        return WorkflowResult(success=False, workflow=self.workflow_name, data=values.to_dict(), errors=[error])

    def _trusted_claimed_retry(self, db, payload, run_id):
        if not isinstance(payload, dict) or not {"execution_id", "mission_id", "worker_name", "retry_count", "max_retries"}.issubset(payload):
            return False
        execution = db.get(Execution, payload["execution_id"])
        mission = db.get(MissionRecord, payload["mission_id"])
        worker = db.get(Worker, payload["worker_name"])
        if execution is None or mission is None or worker is None:
            return False
        if execution.status != "RETRYING" or mission.status != "RUNNING":
            return False
        if execution.mission_id != mission.id or execution.worker_name != worker.name:
            return False
        if worker.status != "BUSY" or worker.current_mission_id != mission.id:
            return False
        try:
            import json
            stored = json.loads(execution.input_data or "{}")
        except (TypeError, ValueError):
            return False
        return stored.get("content_generation_run_id") == run_id

    @staticmethod
    def _has_retry_metadata(payload):
        return isinstance(payload, dict) and any(
            key in payload
            for key in ("execution_id", "mission_id", "worker_name", "retry_count", "max_retries")
        )

    def _retry_remains(self, payload):
        retry_count = payload.get("retry_count", 0) if isinstance(payload, dict) else 0
        max_retries = payload.get("max_retries", 3) if isinstance(payload, dict) else 3
        if isinstance(retry_count, bool) or isinstance(max_retries, bool) or not isinstance(retry_count, int) or not isinstance(max_retries, int):
            return False
        task = Task(self.workflow_name, {}, max_retries=max_retries)
        task.retry_count = retry_count
        return RetryPolicy().execute_retry(task)

    def execute(self, payload):
        try:
            values = ContentGenerationWorkflowPayload.from_payload(payload)
        except ValueError as error:
            return WorkflowResult(success=False, workflow=self.workflow_name, data={}, errors=[f"validation error: {error}"])
        db = self.session_factory()
        try:
            run = db.get(ContentGenerationRun, values.content_generation_run_id)
            if run is None:
                return self._failure(values, "validation error: content generation run does not exist")
            claimed_retry = self._trusted_claimed_retry(db, payload, run.id)
            if self._has_retry_metadata(payload) and not claimed_retry:
                return self._failure(values, "validation error: content generation retry is not coordinator-owned")
            if run.status == "RETRY_WAIT" and not claimed_retry:
                return self._failure(values, "validation error: content generation retry is not coordinator-owned")
            if claimed_retry and run.status != "RETRY_WAIT":
                return self._failure(values, "validation error: content generation retry run is not resumable")
            request = ContentGenerationRequest(
                content_brief_id=run.content_brief_id,
                provider=run.provider,
                model=run.model,
                prompt_version=run.prompt_version,
                generation_parameters=self._parameters(run),
            )
            generated = self.generation_service_factory(db).generate(
                request,
                defer_retryable_failure=self._retry_remains(payload),
                retry_resume=claimed_retry,
            )
            if generated.failure is not None:
                return self._failure(values, ContentProviderFailureAdapter.to_classifier_text(generated.failure))
            if generated.status != "COMPLETED" or generated.artifact_id is None:
                return self._failure(values, "validation error: content generation run is not executable")
            evaluation = self.evaluator_factory(db).evaluate(generated.artifact_id)
            result = ContentGenerationWorkflowResult(
                content_brief_id=run.content_brief_id,
                content_generation_run_id=generated.generation_run_id,
                artifact_id=generated.artifact_id,
                evaluation_id=evaluation.evaluation_id,
                evaluation_decision=evaluation.decision,
            )
            return WorkflowResult(success=True, workflow=self.workflow_name, data=result.to_dict(), errors=[])
        except Exception:
            return self._failure(values, "validation error: content generation workflow failed")
        finally:
            db.close()
