"""Launch one DistributionRun through the frozen durable Mission runtime."""
import json
from dataclasses import dataclass
from app.distribution.mission_contracts import CONTENT_DISTRIBUTION_CAPABILITY, CONTENT_DISTRIBUTION_MISSION_NAME, CONTENT_DISTRIBUTION_WORKFLOW, DistributionWorkflowPayload, distribution_mission_idempotency_key
from app.mission.manager import MissionManager
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.repositories.mission_repository import MissionRepository

@dataclass(frozen=True)
class ContentDistributionMissionLaunchResult:
    distribution_run_id: str; mission_id: str; mission_status: str; workflow: str; required_capability: str | None; idempotency_key: str; worker_name: str | None; result_success: bool | None; result_error: str | None; result_data: dict | None = None

class ContentDistributionMissionLaunchService:
    mission_name=CONTENT_DISTRIBUTION_MISSION_NAME; workflow_name=CONTENT_DISTRIBUTION_WORKFLOW; required_capability=CONTENT_DISTRIBUTION_CAPABILITY; objective="publish approved content to configured destination"
    def __init__(self, mission_manager=None, session_factory=None):
        self.mission_manager=mission_manager or MissionManager(session_factory=session_factory)
        self.session_factory=session_factory or self.mission_manager.session_factory
    def _record(self, run_id, key):
        db=self.session_factory()
        try:
            record=MissionRepository(db).get_by_idempotency_key(key)
            if not record: return None
            data=json.loads(record.result_data) if isinstance(record.result_data,str) and record.result_data else record.result_data
            return ContentDistributionMissionLaunchResult(run_id,record.id,record.status,record.workflow_name,record.required_capability,record.idempotency_key,record.current_worker_name,True if record.status=="COMPLETED" else False if record.status=="FAILED" else None,record.last_error,data.get("data",data) if isinstance(data,dict) else None)
        finally: db.close()
    def launch(self, distribution_run_id):
        key=distribution_mission_idempotency_key(distribution_run_id); existing=self._record(distribution_run_id,key)
        if existing: return existing
        db=self.session_factory()
        try:
            run=DistributionRunRepository(db).get_by_id(distribution_run_id)
            if run is None: raise ValueError("distribution run does not exist")
            if run.status!="CREATED": raise RuntimeError(f"distribution run is already {run.status.lower()}")
        finally: db.close()
        self.mission_manager.launch(self.mission_name,self.objective,self.workflow_name,DistributionWorkflowPayload(distribution_run_id).to_dict(),self.required_capability,key)
        result=self._record(distribution_run_id,key)
        if result is None: raise RuntimeError("durable distribution mission could not be recovered after launch")
        return result
