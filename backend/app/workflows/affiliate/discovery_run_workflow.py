"""Mission workflow boundary for one durable affiliate discovery run."""

from __future__ import annotations

from app.database.session import SessionLocal
from app.discovery.contracts import DiscoveryRunStatus
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.retry.failure_classifier import FailureClassifier
from app.retry.retry_policy import RetryPolicy
from app.task_queue.task import Task
from app.workflow_engine.workflow_result import WorkflowResult
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService


class AffiliateDiscoveryRunWorkflow:
    """Delegate durable discovery execution without owning Mission or Retry state."""

    workflow_name = "affiliate_discovery_run"

    def __init__(
        self,
        session_factory=SessionLocal,
        orchestration_factory=DiscoveryRunOrchestrationService,
        failure_classifier=None,
        retry_policy=None,
    ):
        self.session_factory = session_factory
        self.orchestration_factory = orchestration_factory
        self.failure_classifier = failure_classifier or FailureClassifier()
        self.retry_policy = retry_policy or RetryPolicy()

    @staticmethod
    def _integer(payload, name, default, minimum):
        value = payload.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
        return value

    def _payload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("workflow payload is required")
        run_id = payload.get("discovery_run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("discovery_run_id is required")
        return {
            "discovery_run_id": run_id,
            "top_n": self._integer(payload, "top_n", 1, 1),
            "minimum_score": self._integer(payload, "minimum_score", 40, 0),
            "minimum_evidence_confidence": self._integer(payload, "minimum_evidence_confidence", 70, 0),
            "retry_count": self._integer(payload, "retry_count", 0, 0),
            "max_retries": self._integer(payload, "max_retries", 3, 0),
        }

    @staticmethod
    def _canonical_error(error):
        message = str(error).strip() or "discovery workflow failed"
        lowered = message.lower()
        if "429" in lowered and "rate limit" not in lowered:
            return f"rate limit: {message}"
        if "provider unavailable" in lowered and "upstream unavailable" not in lowered:
            return f"upstream unavailable: {message}"
        return message

    def _another_retry_remains(self, retry_count, max_retries):
        """Use the frozen policy against a disposable task, exactly as TaskExecutor does."""
        task = Task(self.workflow_name, {}, max_retries=max_retries)
        task.retry_count = retry_count
        return self.retry_policy.execute_retry(task)

    def _failure_result(self, run_id, error, failure, retry_count, max_retries, status):
        return WorkflowResult(
            success=False,
            workflow=self.workflow_name,
            data={
                "discovery_run_id": run_id,
                "status": status,
                "failure_type": failure["failure_type"],
                "retryable": failure["retryable"],
                "retry_count": retry_count,
                "max_retries": max_retries,
            },
            errors=[error],
        )

    @staticmethod
    def _success_result(run_id, result):
        run = result.run
        return WorkflowResult(
            success=True,
            workflow=AffiliateDiscoveryRunWorkflow.workflow_name,
            data={
                "discovery_run_id": run_id,
                "status": run.status,
                "ranked_candidate_ids": list(result.ranked_candidate_ids),
                "selected_candidate_ids": list(result.selected_candidate_ids),
                "candidate_count": run.candidate_count,
                "verified_count": run.verified_count,
                "selected_count": run.selected_count,
            },
            errors=[],
        )

    def execute(self, payload):
        try:
            values = self._payload(payload)
        except ValueError as error:
            return self._failure_result(None, str(error), self.failure_classifier.classify(str(error)), 0, 3, None)

        db = self.session_factory()
        try:
            runs = DiscoveryRunRepository(db)
            try:
                result = self.orchestration_factory(db).execute(
                    values["discovery_run_id"],
                    values["top_n"],
                    values["minimum_score"],
                    values["minimum_evidence_confidence"],
                    defer_terminal_failure=True,
                )
                return self._success_result(values["discovery_run_id"], result)
            except Exception as error:
                rollback = getattr(db, "rollback", None)
                if rollback:
                    rollback()
                canonical_error = self._canonical_error(error)
                failure = self.failure_classifier.classify(canonical_error)
                run = runs.get_by_id(values["discovery_run_id"])

                # Pre-existing RUNNING/FAILED states must never be reopened by
                # this workflow. Deferred errors are the only path restored to CREATED.
                if run is not None and run.status == DiscoveryRunStatus.CREATED.value:
                    retrying = failure["retryable"] and self._another_retry_remains(
                        values["retry_count"], values["max_retries"]
                    )
                    target = DiscoveryRunStatus.CREATED if retrying else DiscoveryRunStatus.FAILED
                    run = runs.update_status(run.id, target, canonical_error)

                return self._failure_result(
                    values["discovery_run_id"], canonical_error, failure,
                    values["retry_count"], values["max_retries"],
                    run.status if run is not None else None,
                )
        finally:
            db.close()
