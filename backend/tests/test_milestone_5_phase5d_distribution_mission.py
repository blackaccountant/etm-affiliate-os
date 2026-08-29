"""Isolated Phase 5D initial distribution Mission proof."""
import socket
import pytest
from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import DistributionAdapterMetadata, DistributionFailureCategory, DistributionPublishResult, DistributionStatusLookupState, DistributionValidationResult
from app.mission.manager import MissionManager
from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.services.content_distribution_mission_launch_service import ContentDistributionMissionLaunchService
from app.services.distribution_run_service import DistributionRunService
from app.workflows.distribution.distribution_publish_workflow import DistributionPublishWorkflow
from app.workforce.manager import WorkforceManager
from tests.test_milestone_5_phase5b_distribution_domain import source

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
 import app.database.session as s
 calls=[]
 def bad(*a,**k): calls.append(1); raise AssertionError("configured infrastructure forbidden")
 class E:
  def connect(self,*a,**k): bad()
 monkeypatch.setattr(s,"SessionLocal",bad); monkeypatch.setattr(s,"engine",E()); monkeypatch.setattr(socket,"create_connection",bad); monkeypatch.setattr(socket.socket,"connect",bad)
 yield
 assert not calls

class Fake(DistributionAdapter):
 def __init__(self,factory, outcome=None): self.factory=factory; self.outcome=outcome; self.validation_calls=self.publish_calls=0; self.body=None; self.observed_publishing=False
 @property
 def metadata(self): return DistributionAdapterMetadata("fake",True,True)
 def validate_target(self,r): self.validation_calls+=1; return DistributionValidationResult(True,"ok")
 def publish(self,r):
  self.publish_calls+=1; self.body=r.content_body; db=self.factory();
  try: self.observed_publishing=db.get(DistributionRun,r.distribution_run_id).status=="PUBLISHING" and db.get(DistributionRun,r.distribution_run_id).publishing_started_at is not None
  finally: db.close()
  if self.outcome: return DistributionPublishResult(False,failure_category=self.outcome,safe_message="safe")
  from datetime import datetime,timezone
  return DistributionPublishResult(True,"post","https://fake.invalid/post",datetime.now(timezone.utc),{"platform_status":"published"})
 def get_publish_status(self,r): raise NotImplementedError

class Engine:
 def __init__(self,w): self.w=w; self.calls=0
 def run(self,workflow_name,payload): self.calls+=1; return self.w.execute(payload)

def setup(db,factory,*,workers=True,outcome=None,prepared="prepared body"):
 source(db); run=DistributionRunService(db).create(__import__('app.distribution.contracts',fromlist=['CreateDistributionRunRequest']).CreateDistributionRunRequest("artifact","evaluation","fake","account","destination",prepared))
 fake=Fake(factory,outcome); reg=DistributionAdapterRegistry(); reg.register(fake); workflow=DistributionPublishWorkflow(factory,reg); manager=MissionManager(workforce=WorkforceManager(load_defaults=workers),session_factory=factory); manager.executor.engine=Engine(workflow); return run,fake,ContentDistributionMissionLaunchService(manager),manager,workflow

def state(db,run,mission): db.expire_all(); return db.get(DistributionRun,run.id),db.get(MissionRecord,mission),db.query(Execution).filter_by(mission_id=mission).all(),db.get(Worker,"Content Writer")

def test_success_uses_only_prepared_body_and_persists_publishing_before_call(db_session,db_session_factory):
 run,fake,launcher,_m,_w=setup(db_session,db_session_factory); artifact=db_session.get(__import__('app.models.generated_content_artifact',fromlist=['GeneratedContentArtifact']).GeneratedContentArtifact,"artifact"); artifact.body="source body"; db_session.commit()
 result=launcher.launch(run.id); row,mission,executions,worker=state(db_session,run,result.mission_id)
 assert fake.body=="prepared body" and fake.observed_publishing and row.status==mission.status=="COMPLETED" and row.external_post_id=="post"
 assert len(executions)==1 and executions[0].status=="COMPLETED" and worker.status=="ONLINE" and artifact.body=="source body"

@pytest.mark.parametrize("corrupt",["corrupted body",None])
def test_integrity_mismatch_blocks_validation_and_publish(db_session,db_session_factory,corrupt):
 run,fake,launcher,_m,_w=setup(db_session,db_session_factory); row=db_session.get(DistributionRun,run.id)
 if corrupt is None: row.payload_fingerprint="0"*64
 else: row.prepared_content_body=corrupt
 db_session.commit(); result=launcher.launch(run.id); row,mission,executions,worker=state(db_session,run,result.mission_id)
 assert fake.validation_calls==fake.publish_calls==0 and row.status==mission.status=="FAILED" and len(executions)==1 and executions[0].status=="FAILED" and worker.status=="ONLINE"

@pytest.mark.parametrize("category,expected,worker_status",[(DistributionFailureCategory.RATE_LIMIT,"RETRY_WAIT","BUSY"),(DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT,"RECONCILIATION_REQUIRED","ONLINE"),(DistributionFailureCategory.AUTHENTICATION,"FAILED","ONLINE")])
def test_failure_categories_are_durable_and_safe(db_session,db_session_factory,category,expected,worker_status):
 run,fake,launcher,_m,_w=setup(db_session,db_session_factory,outcome=category); result=launcher.launch(run.id); row,mission,executions,worker=state(db_session,run,result.mission_id)
 assert row.status==expected and fake.publish_calls==1 and worker.status==worker_status
 assert (mission.status,executions[0].status)==(("RETRY_WAIT","QUEUED") if expected=="RETRY_WAIT" else ("FAILED","FAILED"))

def test_waiting_duplicate_and_stale_direct_execution_do_not_publish(db_session,db_session_factory):
 run,fake,launcher,manager,workflow=setup(db_session,db_session_factory,workers=False); first=launcher.launch(run.id); second=launcher.launch(run.id)
 assert first.mission_id==second.mission_id and fake.publish_calls==0 and db_session.query(Execution).count()==0
 db_session.get(DistributionRun,run.id).status="PUBLISHING"; db_session.commit(); assert workflow.execute({"distribution_run_id":run.id}).success is False and fake.publish_calls==0
