from types import SimpleNamespace
import httpx
import pytest
from pydantic import ValidationError
from app.api.distribution import PilotCmsPublishPayload
from app.api.distribution import pilot_cms_publish
from app.core.config import settings
from app.distribution.adapters.wordpress import WordPressDistributionAdapter, deterministic_wordpress_slug
from app.distribution.contracts import DistributionFailureCategory, DistributionStatusLookupState
from app.services.pilot_cms_publication_service import PilotCmsPublicationService
from app.workflows.distribution.distribution_publish_workflow import DistributionPublishWorkflow
from app.distribution.contracts import payload_fingerprint_for_body, DistributionValidationResult, DistributionPublishResult
from app.workflows.distribution.distribution_reconcile_workflow import DistributionReconcileWorkflow
from app.distribution.contracts import DistributionStatusResult
from app.distribution.distribution_reconcile_lifecycle_participant import DistributionReconcileLifecycleParticipant
from app.models.execution import Execution


def _workflow_fakes(monkeypatch, fingerprint, rendered=None):
    body="prepared"; run=SimpleNamespace(id="run",status="CREATED",platform="wordpress",account_reference="a",destination="d",prepared_content_body=body,payload_fingerprint=fingerprint,generated_content_artifact_id="artifact",content_evaluation_id="evaluation",scheduled_for=None)
    artifact=SimpleNamespace(id="artifact",generation_run_id="g"); evaluation=SimpleNamespace(id="evaluation",artifact_id="artifact",generation_run_id="g",decision="APPROVED",approved=True)
    class Db:
        def get(self, cls, key): return run if cls.__name__=="DistributionRun" else artifact if cls.__name__=="GeneratedContentArtifact" else evaluation
        def close(self): pass
    class Repo:
        def __init__(self, db): pass
        def transition_owned(self, run_id, authority, expected_statuses, status, values):
            run.status=status
            for k,v in values.items(): setattr(run,k,v)
            return run
    calls={"render":0,"publish":0}
    class Resolver:
        def __init__(self,db):pass
        def render_wordpress_body(self, run): calls["render"]+=1; return rendered or "rendered"
    class Adapter:
        metadata=SimpleNamespace(supports_status_lookup=True)
        def validate_target(self, request): return DistributionValidationResult(valid=True)
        def publish(self, request): calls["publish"]+=1; calls["body"]=request.content_body; return DistributionPublishResult(success=True,external_post_id="p",external_url="https://example.invalid/p",published_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    monkeypatch.setattr("app.workflows.distribution.distribution_publish_workflow.DistributionRunRepository",Repo)
    monkeypatch.setattr("app.workflows.distribution.distribution_publish_workflow.PilotCmsPublicationService",Resolver)
    monkeypatch.setattr("app.workflows.distribution.distribution_publish_workflow.current_execution_runtime_context",lambda:SimpleNamespace(authority=SimpleNamespace(),is_recovery=False,mission_id="m"))
    return DistributionPublishWorkflow(session_factory=lambda:Db(),adapter_registry=SimpleNamespace(resolve=lambda p:Adapter())),run,calls

def test_workflow_invalid_fingerprint_blocks_render_and_publish(monkeypatch):
    workflow,run,calls=_workflow_fakes(monkeypatch,"0"*64); before=(run.prepared_content_body,run.payload_fingerprint)
    result=workflow.execute({"distribution_run_id":"run"})
    assert not result.success and calls=={"render":0,"publish":0} and (run.prepared_content_body,run.payload_fingerprint)==before

def test_workflow_valid_fingerprint_renders_only_after_integrity(monkeypatch):
    workflow,run,calls=_workflow_fakes(monkeypatch,payload_fingerprint_for_body("prepared"),"rendered-body"); before=(run.prepared_content_body,run.payload_fingerprint)
    result=workflow.execute({"distribution_run_id":"run"})
    assert result.success and calls["render"]==1 and calls["publish"]==1 and calls["body"]=="rendered-body" and (run.prepared_content_body,run.payload_fingerprint)==before

def test_ambiguous_publish_enters_reconciliation_required(monkeypatch):
    workflow,run,calls=_workflow_fakes(monkeypatch,payload_fingerprint_for_body("prepared"))
    class Adapter:
        metadata=SimpleNamespace(supports_status_lookup=True)
        def validate_target(self,r):return DistributionValidationResult(valid=True)
        def publish(self,r):calls["publish"]+=1;return DistributionPublishResult(success=False,failure_category=DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT,safe_message="ambiguous")
    workflow.adapter_registry=SimpleNamespace(resolve=lambda p:Adapter())
    result=workflow.execute({"distribution_run_id":"run"})
    assert not result.success and run.status=="RECONCILIATION_REQUIRED" and calls["publish"]==1

def test_reconcile_published_uses_status_only(monkeypatch):
    run=SimpleNamespace(id="run",status="RECONCILIATION_REQUIRED",platform="wordpress",account_reference="a",destination="d",external_post_id=None)
    class Db:
        def get(self,*a):return run
        def close(self):pass
    class Repo:
        def __init__(self,db):pass
        def claim_reconciliation(self,*a):run.status="RECONCILING";return run
        def resume_reconciliation(self,*a):return run
        def transition_owned(self,*a,**kw):
            run.status=kw["status"]
            for k,v in kw.get("values",{}).items():setattr(run,k,v)
            return run
    calls={"publish":0,"status":0}
    class Adapter:
        metadata=SimpleNamespace(supports_status_lookup=True)
        def publish(self,r):calls["publish"]+=1
        def get_publish_status(self,r):
            calls["status"]+=1
            return DistributionStatusResult(state="PUBLISHED",external_post_id="post",external_url="https://example.invalid/p",published_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    monkeypatch.setattr("app.workflows.distribution.distribution_reconcile_workflow.DistributionRunRepository",Repo)
    monkeypatch.setattr("app.workflows.distribution.distribution_reconcile_workflow.current_execution_runtime_context",lambda:SimpleNamespace(authority=SimpleNamespace(),is_recovery=False))
    result=DistributionReconcileWorkflow(session_factory=lambda:Db(),adapter_registry=SimpleNamespace(resolve=lambda p:Adapter())).execute({"distribution_run_id":"run"})
    assert result.success and run.status=="COMPLETED" and run.external_post_id=="post" and calls=={"publish":0,"status":1}

def test_reconcile_not_found_creates_generation_scoped_followup(monkeypatch):
    run=SimpleNamespace(id="run",status="RECONCILIATION_REQUIRED",platform="wordpress",account_reference="a",destination="d",external_post_id=None,publish_generation=0,failure_category="AMBIGUOUS_SUBMIT_RESULT",error_summary="ambiguous")
    execution=SimpleNamespace(input_data='{"distribution_run_id":"run"}')
    class Db:
        def get(self,cls,key):return execution if cls is Execution else run
        def close(self):pass
        def query(self,cls):
            class Q:
                def filter(self,*a):return self
                def with_for_update(self):return self
                def one_or_none(self):return run
            return Q()
    class Repo:
        def __init__(self,db):pass
        def claim_reconciliation(self,*a):run.status="RECONCILING";return run
        def resume_reconciliation(self,*a):return run
        def transition_owned(self,*a,**kw):run.status=kw["status"];return run
    calls={"status":0,"publish":0}
    class Adapter:
        metadata=SimpleNamespace(supports_status_lookup=True)
        def publish(self,r):calls["publish"]+=1
        def get_publish_status(self,r):calls["status"]+=1;return DistributionStatusResult(state="NOT_FOUND")
    authority=SimpleNamespace(execution_id=7)
    monkeypatch.setattr("app.workflows.distribution.distribution_reconcile_workflow.DistributionRunRepository",Repo)
    monkeypatch.setattr("app.workflows.distribution.distribution_reconcile_workflow.current_execution_runtime_context",lambda:SimpleNamespace(authority=authority,is_recovery=False))
    result=DistributionReconcileWorkflow(session_factory=lambda:Db(),adapter_registry=SimpleNamespace(resolve=lambda p:Adapter())).execute({"distribution_run_id":"run"})
    spec=DistributionReconcileLifecycleParticipant().apply(Db(),authority,"COMPLETED",{"workflow":"distribution_reconcile","data":result.data})
    assert calls=={"status":1,"publish":0} and run.status=="CREATED" and run.publish_generation==1
    assert spec.workflow=="distribution_publish" and spec.idempotency_key=="distribution-publish:run:1"

class Response:
    def __init__(self, code, data=None): self.status_code,self.data=code,([] if data is None else data)
    def json(self): return self.data

def request(): return SimpleNamespace(distribution_run_id="run",content_body="body",payload_fingerprint="a"*64,destination="d",correlation_key="distribution:run",scheduled_for=None,generated_content_artifact_id="a",content_evaluation_id="e",platform="wordpress",account_reference="a")
def post(): return {"id":1,"link":"https://example.invalid/p","date_gmt":"2026-09-07T12:00:00Z","status":"publish"}
def configured(monkeypatch):
    monkeypatch.setattr(settings,"CMS_WORDPRESS_BASE_URL","https://example.invalid");monkeypatch.setattr(settings,"CMS_WORDPRESS_USERNAME","dummy");monkeypatch.setattr(settings,"CMS_WORDPRESS_APP_PASSWORD","dummy-secret")

def test_metadata_and_historical_slug():
    m=WordPressDistributionAdapter().metadata;assert (m.platform,m.supports_status_lookup,m.supports_native_idempotency)==("wordpress",True,False);assert deterministic_wordpress_slug("run")=="distribution-acba25512100f80b56"
def test_lookup_precedes_post(monkeypatch):
    configured(monkeypatch);calls=[]
    def fake(method,url,**kw): calls.append(method);return Response(200,[]) if method=="GET" else Response(201,post())
    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",fake);assert WordPressDistributionAdapter().publish(request()).success;assert calls==["GET","POST"]
def test_existing_slug_reuses_without_post(monkeypatch):
    configured(monkeypatch);calls=[]
    def fake(method,url,**kw): calls.append(method);return Response(200,[post()])
    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",fake);assert WordPressDistributionAdapter().publish(request()).success;assert calls==["GET"]
def test_multiple_matches_fail_closed(monkeypatch):
    configured(monkeypatch);monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",lambda *a,**k:Response(200,[post(),post()]));assert WordPressDistributionAdapter().publish(request()).failure_category is DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT
def test_post_timeout_ambiguous_lookup_timeout_pre_submit(monkeypatch):
    configured(monkeypatch)
    def post_timeout(method,url,**kw):
        if method=="GET": return Response(200,[])
        raise httpx.TimeoutException("dummy")
    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",post_timeout);assert WordPressDistributionAdapter().publish(request()).failure_category is DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT
    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",lambda *a,**k:(_ for _ in ()).throw(httpx.TimeoutException("dummy")));assert WordPressDistributionAdapter().publish(request()).failure_category is DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT
def test_malformed_success_ambiguous(monkeypatch):
    configured(monkeypatch);monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",lambda method,url,**k:Response(200,[]) if method=="GET" else Response(201,{"id":1}));assert WordPressDistributionAdapter().publish(request()).failure_category is DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT
def test_status_lookup(monkeypatch):
    configured(monkeypatch);monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",lambda method,url,**k:Response(200,post()) if url.endswith("/1") else Response(200,[post()]));a=WordPressDistributionAdapter();assert a.get_publish_status(SimpleNamespace(distribution_run_id="run",platform="wordpress",account_reference="a",destination="d",external_post_id="1")).state is DistributionStatusLookupState.PUBLISHED
def test_auth_permission_secret_safe(monkeypatch):
    configured(monkeypatch)
    for code,category in ((401,DistributionFailureCategory.AUTHENTICATION),(403,DistributionFailureCategory.PERMISSION_DENIED)):
        monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request",lambda *a,**k:Response(code,[]));r=WordPressDistributionAdapter().publish(request());assert r.failure_category is category and "dummy-secret" not in r.safe_message
def test_caller_authority_forbidden():
    for field in ("tracking_code","affiliate_url","external_post_id","wordpress_password"):
        with pytest.raises(ValidationError): PilotCmsPublishPayload(distribution_run_id="r",**{field:"x"})

def test_exact_lineage_cardinality_and_deterministic_absolute_render(monkeypatch):
    monkeypatch.setattr(settings,"PUBLIC_API_BASE_URL","https://api.example/ ")
    run=SimpleNamespace(id="run",prepared_content_body="Hi {{affiliate_link}}",payload_fingerprint="f")
    pub,ctx,link=SimpleNamespace(id="p"),SimpleNamespace(id="c",affiliate_program_id=1),SimpleNamespace(affiliate_program_id=1,tracking_code="track")
    class Q:
        def __init__(self,v):self.v=v
        def filter_by(self,**k):return self
        def all(self):return self.v
    class Db:
        def get(self,*a):return run
        def query(self,model):return Q([pub] if model.__name__=="AttributionPublication" else [ctx] if model.__name__=="AttributionContext" else [link])
    before=run.prepared_content_body;service=PilotCmsPublicationService(Db());body=service.render_wordpress_body(run)
    assert "https://api.example/affiliate-links/go/track" in body and run.prepared_content_body==before and body==service.render_wordpress_body(run)

def test_lineage_rejects_multiple_and_program_conflict(monkeypatch):
    monkeypatch.setattr(settings,"PUBLIC_API_BASE_URL","https://api.example")
    run=SimpleNamespace(id="run",prepared_content_body="Hi")
    class Q:
        def __init__(self,v):self.v=v
        def filter_by(self,**k):return self
        def all(self):return self.v
    class Db:
        def get(self,*a):return run
        def query(self,model):return Q([SimpleNamespace(id="p")] if model.__name__=="AttributionPublication" else [SimpleNamespace(id="c",affiliate_program_id=1)] if model.__name__=="AttributionContext" else [SimpleNamespace(affiliate_program_id=1,tracking_code="a"),SimpleNamespace(affiliate_program_id=1,tracking_code="b")])
    with pytest.raises(ValueError):PilotCmsPublicationService(Db()).render_wordpress_body(run)

def test_pilot_endpoint_activates_durable_mission(monkeypatch):
    run=SimpleNamespace(id="run",status="CREATED")
    class Db:
        def get(self,*a):return run
    called=[]
    class Launcher:
        def __init__(self,**kwargs):pass
        def launch(self,run_id):
            called.append(run_id)
            return SimpleNamespace(distribution_run_id=run_id,mission_id="m",mission_status="RUNNING",workflow="distribution_publish")
    monkeypatch.setattr("app.api.distribution.ContentDistributionMissionLaunchService",Launcher)
    result=pilot_cms_publish(PilotCmsPublishPayload(distribution_run_id="run"),Db())
    assert called==["run"] and result["workflow"]=="distribution_publish"

def test_completed_replay_does_not_activate_mission(monkeypatch):
    run=SimpleNamespace(id="run",status="COMPLETED",external_post_id="post",external_url="https://example.invalid/post")
    class Db:
        def get(self,*a):return run
    class Launcher:
        def __init__(self,**kwargs):raise AssertionError("must not activate")
    monkeypatch.setattr("app.api.distribution.ContentDistributionMissionLaunchService",Launcher)
    assert pilot_cms_publish(PilotCmsPublishPayload(distribution_run_id="run"),Db())["external_post_id"]=="post"
