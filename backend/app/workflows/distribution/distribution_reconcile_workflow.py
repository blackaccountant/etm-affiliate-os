"""Status-only reconciliation; it never invokes adapter.publish."""
from datetime import datetime,timezone
from app.database.session import SessionLocal
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import DistributionStatusRequest,DistributionStatusLookupState
from app.distribution.mission_contracts import DistributionWorkflowPayload
from app.models.distribution_run import DistributionRun
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.execution_runtime_context import current_execution_runtime_context
from app.workflow_engine.workflow_result import WorkflowResult
class DistributionReconcileWorkflow:
 workflow_name="distribution_reconcile"
 def __init__(self,session_factory=SessionLocal,adapter_registry=None):self.session_factory=session_factory;self.adapter_registry=adapter_registry or DistributionAdapterRegistry()
 def execute(self,payload):
  try:v=DistributionWorkflowPayload.from_payload(payload)
  except ValueError as e:return WorkflowResult(False,self.workflow_name,{},errors=[f"validation error: {e}"])
  db=self.session_factory()
  try:
   run=db.get(DistributionRun,v.distribution_run_id)
   if run is None:return WorkflowResult(False,self.workflow_name,v.to_dict(),errors=["validation error: distribution run does not exist"])
   context=current_execution_runtime_context()
   if context is None:return WorkflowResult(False,self.workflow_name,v.to_dict(),errors=["execution runtime authority is required"])
   repository=DistributionRunRepository(db)
   if run.status=="RECONCILING" and context.is_recovery:
    run=repository.resume_reconciliation(run.id,context.authority)
   else:
    run=repository.claim_reconciliation(run.id,context.authority)
   if run is None:return WorkflowResult(True,self.workflow_name,{"distribution_run_id":v.distribution_run_id,"reconciliation_state":"UNKNOWN","safe_message":"reconciliation already owned or unresolved"},errors=[])
   try:adapter=self.adapter_registry.resolve(run.platform)
   except Exception:
    repository.transition_owned(run.id,context.authority,expected_statuses=("RECONCILING",),status="RECONCILIATION_REQUIRED",values={"failure_category":"AMBIGUOUS_SUBMIT_RESULT","error_summary":"manual reconciliation required"})
    return WorkflowResult(True,self.workflow_name,{"distribution_run_id":run.id,"reconciliation_state":"MANUAL_REQUIRED","safe_message":"manual reconciliation required"},errors=[])
   if not adapter.metadata.supports_status_lookup:
    repository.transition_owned(run.id,context.authority,expected_statuses=("RECONCILING",),status="RECONCILIATION_REQUIRED",values={"failure_category":"AMBIGUOUS_SUBMIT_RESULT","error_summary":"manual reconciliation required"})
    return WorkflowResult(True,self.workflow_name,{"distribution_run_id":run.id,"platform":run.platform,"reconciliation_state":"MANUAL_REQUIRED","safe_message":"manual reconciliation required"},errors=[])
   result=adapter.get_publish_status(DistributionStatusRequest(run.id,run.platform,run.account_reference,run.destination,run.external_post_id))
   data={"distribution_run_id":run.id,"platform":run.platform,"reconciliation_state":result.state.value,"external_post_id":result.external_post_id,"external_url":result.external_url,"published_at":result.published_at.isoformat() if result.published_at else None,"safe_message":None}
   if result.state is DistributionStatusLookupState.PUBLISHED:
    repository.transition_owned(run.id,context.authority,expected_statuses=("RECONCILING",),status="COMPLETED",values={"external_post_id":result.external_post_id,"external_url":result.external_url,"result_metadata":result.safe_metadata,"completed_at":datetime.now(timezone.utc),"failure_category":None,"error_summary":None})
   elif result.state is DistributionStatusLookupState.NOT_FOUND:
    data["safe_message"]="external publish was not found; follow-up publish will be activated"
   else:
    repository.transition_owned(run.id,context.authority,expected_statuses=("RECONCILING",),status="RECONCILIATION_REQUIRED",values={"failure_category":"AMBIGUOUS_SUBMIT_RESULT","error_summary":"external publish result remains unknown"});data["safe_message"]="external publish result remains unknown"
   return WorkflowResult(True,self.workflow_name,data,errors=[])
  finally:db.close()
