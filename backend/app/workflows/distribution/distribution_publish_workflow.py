"""Initial-only publication of one immutable DistributionRun payload."""
from datetime import datetime, timezone
from app.database.session import SessionLocal
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import DistributionFailureCategory, DistributionPublishRequest, DistributionValidationRequest, DistributionRunStatus, payload_fingerprint_for_body
from app.distribution.exceptions import UnsupportedDistributionPlatformError
from app.distribution.failure_adapter import DistributionFailureAdapter
from app.distribution.mission_contracts import DistributionWorkflowPayload
from app.models.content_evaluation import ContentEvaluation
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.workflow_engine.workflow_result import WorkflowResult

class DistributionPublishWorkflow:
    workflow_name="distribution_publish"
    def __init__(self, session_factory=SessionLocal, adapter_registry=None): self.session_factory=session_factory; self.adapter_registry=adapter_registry or DistributionAdapterRegistry()
    def _failure(self, values, message): return WorkflowResult(False,self.workflow_name,values.to_dict(),errors=[message])
    def _set(self, db, run, status, category=None, error=None, result=None):
        now=datetime.now(timezone.utc); run.status=status; run.updated_at=now; run.failure_category=category; run.error_summary=error
        if status=="PUBLISHING": run.publishing_started_at=now
        if status=="COMPLETED": run.completed_at=now; run.external_post_id=result.external_post_id; run.external_url=result.external_url; run.result_metadata=result.safe_metadata; run.failure_category=run.error_summary=None
        db.commit()
    def _trusted_retry(self, db, payload, run):
        required={"execution_id","mission_id","worker_name","retry_count","max_retries"}
        if not isinstance(payload,dict) or not required.issubset(payload): return False
        execution=db.get(Execution,payload["execution_id"]); mission=db.get(MissionRecord,payload["mission_id"]); worker=db.get(Worker,payload["worker_name"])
        if not execution or not mission or not worker: return False
        if execution.status!="RETRYING" or mission.status!="RUNNING" or worker.status!="BUSY": return False
        if execution.mission_id!=mission.id or execution.worker_name!=worker.name or worker.current_mission_id!=mission.id: return False
        import json
        try: stored=json.loads(execution.input_data or "{}")
        except (TypeError,ValueError): return False
        return stored.get("distribution_run_id")==run.id
    def execute(self,payload):
        try: values=DistributionWorkflowPayload.from_payload(payload)
        except ValueError as e: return WorkflowResult(False,self.workflow_name,{},errors=[f"validation error: {e}"])
        db=self.session_factory()
        try:
            run=db.get(DistributionRun,values.distribution_run_id)
            if run is None: return self._failure(values,"validation error: distribution run does not exist")
            retry=self._trusted_retry(db,payload,run)
            if run.status==DistributionRunStatus.RETRY_WAIT.value:
                if not retry: return self._failure(values,"validation error: distribution retry is not coordinator-owned")
                claimed=db.query(DistributionRun).filter(DistributionRun.id==run.id,DistributionRun.status==DistributionRunStatus.RETRY_WAIT.value).update({DistributionRun.status:"RUNNING"},synchronize_session=False); db.commit()
                if claimed!=1: return self._failure(values,"validation error: distribution retry is not resumable")
                run=db.get(DistributionRun,run.id)
            elif run.status!=DistributionRunStatus.CREATED.value: return self._failure(values,"validation error: distribution run is not executable")
            artifact=db.get(GeneratedContentArtifact,run.generated_content_artifact_id); evaluation=db.get(ContentEvaluation,run.content_evaluation_id)
            if artifact is None or evaluation is None or evaluation.artifact_id!=artifact.id or evaluation.generation_run_id!=artifact.generation_run_id or evaluation.decision!="APPROVED" or evaluation.approved is not True:
                self._set(db,run,"FAILED",DistributionFailureCategory.UNKNOWN_PERMANENT.value,"validation error: distribution lineage is not eligible"); return self._failure(values,"validation error: distribution lineage is not eligible")
            try: integrity=payload_fingerprint_for_body(run.prepared_content_body)==run.payload_fingerprint
            except ValueError: integrity=False
            if not integrity:
                self._set(db,run,"FAILED",DistributionFailureCategory.UNKNOWN_PERMANENT.value,"validation error: distribution payload integrity check failed"); return self._failure(values,"validation error: distribution payload integrity check failed")
            try: adapter=self.adapter_registry.resolve(run.platform)
            except UnsupportedDistributionPlatformError:
                self._set(db,run,"FAILED",DistributionFailureCategory.UNSUPPORTED_PLATFORM.value,"unsupported distribution platform"); return self._failure(values,"unsupported distribution platform")
            validated=adapter.validate_target(DistributionValidationRequest(run.id,run.platform,run.account_reference,run.destination,payload_fingerprint=run.payload_fingerprint))
            if not validated.valid:
                category=validated.failure_category or DistributionFailureCategory.INVALID_DESTINATION; text=DistributionFailureAdapter.to_classifier_text(category); self._set(db,run,"FAILED",category.value,text); return self._failure(values,text)
            if run.status!="RUNNING": self._set(db,run,"RUNNING")
            self._set(db,run,"PUBLISHING")
            try: result=adapter.publish(DistributionPublishRequest(run.id,artifact.id,evaluation.id,run.platform,run.account_reference,run.destination,run.payload_fingerprint,run.prepared_content_body,run.scheduled_for))
            except Exception:
                self._set(db,run,"FAILED",DistributionFailureCategory.UNKNOWN_PERMANENT.value,"permanent distribution provider error"); return self._failure(values,"permanent distribution provider error")
            if result.success:
                self._set(db,run,"COMPLETED",result=result); return WorkflowResult(True,self.workflow_name,{"distribution_run_id":run.id,"generated_content_artifact_id":artifact.id,"content_evaluation_id":evaluation.id,"platform":run.platform,"destination":run.destination,"external_post_id":result.external_post_id,"external_url":result.external_url,"published_at":result.published_at.isoformat()},errors=[])
            category=result.failure_category or DistributionFailureCategory.UNKNOWN_PERMANENT; text=DistributionFailureAdapter.to_classifier_text(category); state="RECONCILIATION_REQUIRED" if category is DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT else "RETRY_WAIT" if category.retryable else "FAILED"; self._set(db,run,state,category.value,text); return self._failure(values,text)
        finally: db.close()
