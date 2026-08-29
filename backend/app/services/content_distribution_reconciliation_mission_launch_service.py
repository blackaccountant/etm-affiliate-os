"""Launch durable, non-republishing reconciliation for one ambiguous run."""
from app.distribution.mission_contracts import CONTENT_DISTRIBUTION_CAPABILITY, CONTENT_DISTRIBUTION_RECONCILIATION_MISSION_NAME, CONTENT_DISTRIBUTION_RECONCILIATION_WORKFLOW, DistributionWorkflowPayload, distribution_reconciliation_mission_idempotency_key
from app.services.content_distribution_mission_launch_service import ContentDistributionMissionLaunchResult
from app.mission.manager import MissionManager
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.repositories.mission_repository import MissionRepository
import json
class ContentDistributionReconciliationMissionLaunchService:
 mission_name=CONTENT_DISTRIBUTION_RECONCILIATION_MISSION_NAME; workflow_name=CONTENT_DISTRIBUTION_RECONCILIATION_WORKFLOW; required_capability=CONTENT_DISTRIBUTION_CAPABILITY; objective="reconcile ambiguous external publish result"
 def __init__(self,mission_manager=None,session_factory=None): self.mission_manager=mission_manager or MissionManager(session_factory=session_factory); self.session_factory=session_factory or self.mission_manager.session_factory
 def _existing(self,run_id,key):
  db=self.session_factory()
  try:
   r=MissionRepository(db).get_by_idempotency_key(key)
   if not r:return None
   data=json.loads(r.result_data) if isinstance(r.result_data,str) and r.result_data else r.result_data
   return ContentDistributionMissionLaunchResult(run_id,r.id,r.status,r.workflow_name,r.required_capability,r.idempotency_key,r.current_worker_name,True if r.status=="COMPLETED" else False if r.status=="FAILED" else None,r.last_error,data.get("data",data) if isinstance(data,dict) else None)
  finally: db.close()
 def launch(self,run_id):
  key=distribution_reconciliation_mission_idempotency_key(run_id); existing=self._existing(run_id,key)
  if existing:return existing
  db=self.session_factory()
  try:
   run=DistributionRunRepository(db).get_by_id(run_id)
   if run is None: raise ValueError("distribution run does not exist")
   if run.status!="RECONCILIATION_REQUIRED": raise RuntimeError("distribution run is not reconciliation-required")
  finally: db.close()
  self.mission_manager.launch(self.mission_name,self.objective,self.workflow_name,DistributionWorkflowPayload(run_id).to_dict(),self.required_capability,key)
  return self._existing(run_id,key)
