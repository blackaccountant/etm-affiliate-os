"""Mission workflow for one durable content-repurposing run."""

import json

from app.database.session import SessionLocal
from app.content_intelligence.content_evaluator import ContentEvaluator
from app.content_intelligence.content_mission_contracts import ContentRepurposingWorkflowPayload, ContentRepurposingWorkflowResult
from app.content_intelligence.content_provider_failure_adapter import ContentProviderFailureAdapter
from app.content_intelligence.generation_contracts import GenerationParameters
from app.content_intelligence.repurposing_contracts import ContentRepurposingRequest
from app.content_intelligence.repurposing_service import ContentRepurposingService
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.retry.retry_policy import RetryPolicy
from app.task_queue.task import Task
from app.workflow_engine.workflow_result import WorkflowResult


class ContentRepurposingWorkflow:
    workflow_name = "content_repurpose"

    def __init__(self, session_factory=SessionLocal, repurposing_service_factory=ContentRepurposingService, evaluator_factory=ContentEvaluator):
        self.session_factory = session_factory
        self.repurposing_service_factory = repurposing_service_factory
        self.evaluator_factory = evaluator_factory

    def _failure(self, values, error):
        return WorkflowResult(success=False, workflow=self.workflow_name, data=values.to_dict(), errors=[error])

    @staticmethod
    def _has_retry_metadata(payload):
        return isinstance(payload, dict) and any(key in payload for key in ("execution_id", "mission_id", "worker_name", "retry_count", "max_retries"))

    def _trusted_claimed_retry(self, db, payload, repurposing_run):
        required = {"execution_id", "mission_id", "worker_name", "retry_count", "max_retries"}
        if not isinstance(payload, dict) or not required.issubset(payload):
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
            stored = json.loads(execution.input_data or "{}")
        except (TypeError, ValueError):
            return False
        return stored.get("content_repurposing_run_id") == repurposing_run.id

    def _retry_remains(self, payload):
        retry_count = payload.get("retry_count", 0) if isinstance(payload, dict) else 0
        max_retries = payload.get("max_retries", 3) if isinstance(payload, dict) else 3
        if isinstance(retry_count, bool) or isinstance(max_retries, bool) or not isinstance(retry_count, int) or not isinstance(max_retries, int):
            return False
        task = Task(self.workflow_name, {}, max_retries=max_retries)
        task.retry_count = retry_count
        return RetryPolicy().execute_retry(task)

    @staticmethod
    def _request(repurposing_run, generation_run):
        parameters = generation_run.generation_parameters if isinstance(generation_run.generation_parameters, dict) else {}
        return ContentRepurposingRequest(
            source_artifact_id=repurposing_run.source_artifact_id,
            source_evaluation_id=repurposing_run.source_evaluation_id,
            target_content_type=repurposing_run.target_content_type,
            channel_intent=repurposing_run.channel_intent,
            provider=generation_run.provider,
            model=generation_run.model,
            prompt_version=generation_run.prompt_version,
            generation_parameters=GenerationParameters(temperature=parameters.get("temperature", GenerationParameters().temperature), max_output_tokens=parameters.get("max_output_tokens", GenerationParameters().max_output_tokens)),
            tone_constraints=parameters.get("tone_constraints"),
            format_constraints=parameters.get("format_constraints"),
        )

    def execute(self, payload):
        try:
            values = ContentRepurposingWorkflowPayload.from_payload(payload)
        except ValueError as error:
            return WorkflowResult(success=False, workflow=self.workflow_name, data={}, errors=[f"validation error: {error}"])
        db = self.session_factory()
        try:
            repurposing_run = db.get(ContentRepurposingRun, values.content_repurposing_run_id)
            if repurposing_run is None:
                return self._failure(values, "validation error: content repurposing run does not exist")
            generation_run = db.get(ContentGenerationRun, repurposing_run.generation_run_id)
            if generation_run is None:
                return self._failure(values, "validation error: linked content generation run does not exist")
            claimed_retry = self._trusted_claimed_retry(db, payload, repurposing_run)
            if self._has_retry_metadata(payload) and not claimed_retry:
                return self._failure(values, "validation error: content repurposing retry is not coordinator-owned")
            if generation_run.status == "RETRY_WAIT" and not claimed_retry:
                return self._failure(values, "validation error: content repurposing retry is not coordinator-owned")
            if claimed_retry and generation_run.status != "RETRY_WAIT":
                return self._failure(values, "validation error: content repurposing retry run is not resumable")
            result = self.repurposing_service_factory(db).repurpose(
                self._request(repurposing_run, generation_run),
                defer_retryable_failure=self._retry_remains(payload),
                retry_resume=claimed_retry,
            )
            if result.failure is not None:
                return self._failure(values, ContentProviderFailureAdapter.to_classifier_text(result.failure))
            if result.status != "COMPLETED" or result.artifact_id is None:
                return self._failure(values, "validation error: content repurposing run is not executable")
            evaluation = self.evaluator_factory(db).evaluate(result.artifact_id)
            return WorkflowResult(success=True, workflow=self.workflow_name, data=ContentRepurposingWorkflowResult(
                source_artifact_id=repurposing_run.source_artifact_id,
                content_repurposing_run_id=repurposing_run.id,
                content_generation_run_id=result.generation_run_id,
                result_artifact_id=result.artifact_id,
                evaluation_id=evaluation.evaluation_id,
                evaluation_decision=evaluation.decision,
            ).to_dict(), errors=[])
        except Exception:
            return self._failure(values, "validation error: content repurposing workflow failed")
        finally:
            db.close()
