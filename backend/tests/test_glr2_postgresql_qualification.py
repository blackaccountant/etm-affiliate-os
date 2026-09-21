"""Guarded real-ORM GLR2R1 qualification; never contacts non-local targets."""
import os
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.distribution.contracts import payload_fingerprint_for_body
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.models.mission_record import MissionRecord
from app.services.content_distribution_mission_launch_service import ContentDistributionMissionLaunchService
from app.services.pilot_cms_publication_service import PilotCmsPublicationService

DATABASE="etm_g5_glr2_wordpress_publication_qualification"
RAW=os.getenv("ETM_G5_GLR2_DATABASE_URL"); ROLE=os.getenv("ETM_G5_GLR2_DB_ROLE"); FRESH=os.getenv("ETM_G5_GLR2_DB_FRESHNESS_ATTESTED")
URL=make_url(RAW) if RAW else None
@pytest.fixture
def Session():
    if URL is None: pytest.skip("requires guarded GLR2 local qualification URL")
    if ROLE!="qualification" or not URL.drivername.startswith("postgresql") or URL.host!="127.0.0.1" or URL.port!=5432 or URL.database!=DATABASE or FRESH not in {"1","true","True","TRUE"}: raise RuntimeError("GLR2 local qualification database guard failed")
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False),future=True),expire_on_commit=False)
def _seed(db, *, lineage=True, active=True, mismatch=False):
    t=uuid4().hex; now=datetime.now(timezone.utc)
    d=DiscoveryRun(id=t+'d',input_type='URL',input_value='https://example.test',input_data={},status='COMPLETED',idempotency_key=t+'d',candidate_count=1,verified_count=1,selected_count=1,created_at=now,updated_at=now);db.add(d);db.flush()
    c=DiscoveryCandidate(id=t+'c',run_id=d.id,source_adapter='test',source_type='TEST',source_url=None,vendor_name='v',canonical_domain='example.test',offer_name='o',program_name='p',affiliate_network=None,affiliate_url=None,program_identity_key=t+'p',dedupe_key=t+'k',commission_model='UNKNOWN',verification_status='VERIFIED',disposition='SELECTED',confidence=1,score=1,created_at=now,updated_at=now);db.add(c);db.flush()
    b=ContentBrief(id=t+'b',discovery_run_id=d.id,discovery_candidate_id=c.id,content_type='ARTICLE',channel_intent='SEO',objective='o',call_to_action='CHECK_DETAILS',required_disclosure='AFFILIATE_DISCLOSURE_REQUIRED',key_benefits=[],proof_points=[],target_keywords=[],constraints=[],idempotency_key=t+'b',status='READY',created_at=now,updated_at=now);db.add(b);db.flush()
    g=ContentGenerationRun(id=t+'g',content_brief_id=b.id,idempotency_key=t+'g',provider='test',model='test',prompt_version='v',generation_parameters={},status='COMPLETED',attempt_count=1,created_at=now,updated_at=now);db.add(g);db.flush()
    a=GeneratedContentArtifact(id=t+'a',generation_run_id=g.id,content_brief_id=b.id,content_type='ARTICLE',title='t',hook='h',body='body',call_to_action='CHECK_DETAILS',affiliate_disclosure='AFFILIATE_DISCLOSURE_REQUIRED',claims=[],status='GENERATED',created_at=now,updated_at=now);db.add(a);db.flush()
    e=ContentEvaluation(id=t+'e',artifact_id=a.id,content_brief_id=b.id,generation_run_id=g.id,factual_grounding_score=1,offer_alignment_score=1,intent_alignment_score=1,clarity_score=1,cta_score=1,compliance_score=1,overall_score=1,decision='APPROVED',approved=True,evaluator_version='v',policy_version='v',claim_results=[],compliance_flags=[],unsupported_claims=[],missing_evidence_ids=[],revision_reasons=[],rejection_reasons=[],created_at=now,updated_at=now);db.add(e);db.flush()
    p=Product(name=t,website='https://'+t+'.test',category='t',affiliate_program='t',commission_type='percentage',commission_value='1',affiliate_score=1,grade='A',confidence=1,summary='',recommendation='',status='active');db.add(p);db.flush(); ap=AffiliateProgram(product_id=p.id,program_name=t,commission_type='percentage',commission_value='1',status='active');db.add(ap);db.flush()
    body='prepared'; run=DistributionRun(id=t+'r',generated_content_artifact_id=a.id,content_evaluation_id=e.id,platform='wordpress',account_reference='a',destination='d',status='CREATED',publish_generation=0,reconciliation_generation=0,idempotency_key=t+'r',prepared_content_body=body,payload_fingerprint=payload_fingerprint_for_body(body),created_at=now,updated_at=now);db.add(run);db.flush()
    if lineage:
      pub=AttributionPublication(id=t+'p',distribution_run_id=run.id,created_at=now);db.add(pub);db.flush(); ctx=AttributionContext(id=t+'x',affiliate_program_id=ap.id,attribution_publication_id=pub.id,context_fingerprint=(t*3)[:64],created_at=now);db.add(ctx);db.flush(); link=AffiliateLink(affiliate_program_id=ap.id if not mismatch else p.id,name=t,destination_url='https://example.test',tracking_code=t,is_active=active,attribution_context_id=ctx.id);db.add(link);db.flush()
    return run,t
def test_glr2_postgresql_qualification_guard(Session):
    with Session() as db: assert db.execute(text('SELECT 1')).scalar_one()==1
def test_glr2_postgresql_lineage_authority_scope(Session,monkeypatch):
    monkeypatch.setattr(settings,'PUBLIC_API_BASE_URL','https://api.example');
    with Session() as db:
      run,t=_seed(db);db.commit();before=db.query(AttributionPublication).filter_by(distribution_run_id=run.id).count();assert PilotCmsPublicationService(db).tracking_code_for_run(run.id)==t;assert 'https://api.example/affiliate-links/go/'+t in PilotCmsPublicationService(db).render_wordpress_body(run);assert db.query(AttributionPublication).filter_by(distribution_run_id=run.id).count()==before
def test_glr2_postgresql_no_attribution_mutation_contract(Session):
    with Session() as db:
      run,_=_seed(db,lineage=False);db.commit();
      with pytest.raises(ValueError):PilotCmsPublicationService(db).tracking_code_for_run(run.id)
      assert db.query(AttributionPublication).filter_by(distribution_run_id=run.id).count()==0
def test_glr2_postgresql_prepared_content_authority_contract(Session,monkeypatch):
    monkeypatch.setattr(settings,'PUBLIC_API_BASE_URL','https://api.example');
    with Session() as db: run,_=_seed(db);db.commit();before=(run.prepared_content_body,run.payload_fingerprint);PilotCmsPublicationService(db).render_wordpress_body(run);db.expire_all();stored=db.get(DistributionRun,run.id);assert (stored.prepared_content_body,stored.payload_fingerprint)==before
def test_glr2_postgresql_durable_activation_contract(Session):
    with Session() as db:
      run,_=_seed(db);db.commit(); run_id=run.id
    service=ContentDistributionMissionLaunchService(session_factory=Session)
    first=service.launch(run_id)
    second=service.launch(run_id)
    with Session() as verify:
      rows=verify.query(MissionRecord).filter_by(idempotency_key=f"distribution:{run_id}").all()
      assert len(rows)==1
      record=rows[0]
      assert record.workflow_name=="distribution_publish" and record.required_capability=="content_distribution"
      assert first.mission_id==second.mission_id==record.id
def test_glr2_postgresql_reconciliation_contract(Session):
    with Session() as db:
      run,_=_seed(db);run.status='COMPLETED';run.external_post_id='post';run.external_url='https://example.test/post';run.completed_at=datetime.now(timezone.utc);run.result_metadata={'platform_status':'published'};db.commit();db.expire_all();stored=db.get(DistributionRun,run.id);assert (stored.status,stored.external_post_id,stored.external_url)==('COMPLETED','post','https://example.test/post')
