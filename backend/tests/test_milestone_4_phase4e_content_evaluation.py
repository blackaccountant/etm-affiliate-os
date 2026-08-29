from datetime import datetime, timezone
import pytest
from app.content_intelligence.content_evaluator import ContentEvaluator
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.content_evaluation import ContentEvaluation
from app.models.discovery import DiscoveryRun, DiscoveryCandidate, EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.affiliate_content_asset import AffiliateContentAsset

def seed(db, *, body="A grounded guide. This content contains affiliate links.", disclosure="This content contains affiliate links.", cta="CHECK_DETAILS", claims=None, status="GENERATED"):
    now=datetime.now(timezone.utc); run=DiscoveryRun(id="run",input_type="URL",input_value="https://example.com",status="COMPLETED",idempotency_key="run",candidate_count=1,verified_count=1,selected_count=1,created_at=now,updated_at=now); candidate=DiscoveryCandidate(id="candidate",run_id="run",source_adapter="official",source_type="official",canonical_domain="example.com",program_identity_key="p",dedupe_key="d",commission_model="PERCENT",verification_status="VERIFIED",disposition="SELECTED",created_at=now,updated_at=now); brief=ContentBrief(id="brief",discovery_run_id="run",discovery_candidate_id="candidate",content_type="ARTICLE",channel_intent="SEO",objective="facts",call_to_action="CHECK_DETAILS",required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED",key_benefits=[],proof_points=[],target_keywords=[],constraints=[],idempotency_key="brief",status="READY",created_at=now,updated_at=now); gen=ContentGenerationRun(id="gen",content_brief_id="brief",idempotency_key="gen",provider="fake",model="fake",prompt_version="v1",generation_parameters={},status="COMPLETED",attempt_count=1,created_at=now,updated_at=now); evidence=EvidenceObservation(id="evidence",candidate_id="candidate",claim_type="commission_percent",observed_value=20,source_url="https://example.com",source_type="official",excerpt="20% commission",extractor="test",extractor_version="1",confidence=90,observed_at=now,created_at=now)
    db.add_all([run,candidate,brief,gen,evidence]); db.flush(); db.add(ContentBriefEvidence(id="link",content_brief_id="brief",evidence_observation_id="evidence",usage_role="ECONOMICS",created_at=now)); artifact=GeneratedContentArtifact(id="artifact",generation_run_id="gen",content_brief_id="brief",content_type="ARTICLE",title="Title",hook="Hook",body=body,call_to_action=cta,affiliate_disclosure=disclosure,claims=claims if claims is not None else [{"text":"Earn 20% commission","source_evidence_ids":["evidence"]}],status=status,created_at=now,updated_at=now); db.add(artifact); db.commit(); return artifact

def test_valid_grounded_artifact_is_approved_and_idempotent(db_session):
    artifact=seed(db_session); evaluator=ContentEvaluator(db_session); first=evaluator.evaluate(artifact.id); second=evaluator.evaluate(artifact.id)
    assert first.decision=="APPROVED" and second.evaluation_id==first.evaluation_id and db_session.query(ContentEvaluation).count()==1
    assert db_session.query(ContentGenerationRun).count()==1 and db_session.query(GeneratedContentArtifact).count()==1
    assert db_session.query(Product).count()==db_session.query(AffiliateProgram).count()==db_session.query(AffiliateOpportunity).count()==db_session.query(AffiliateContentAsset).count()==0

@pytest.mark.parametrize("body,disclosure,expected",[("Normal body","", "REVISION_REQUIRED"),("Earn 30% commission. This content contains affiliate links.","This content contains affiliate links.","REJECTED"),("Get a 60-day cookie. This content contains affiliate links.","This content contains affiliate links.","REJECTED"),("Limited time offer. This content contains affiliate links.","This content contains affiliate links.","REVISION_REQUIRED"),("Guaranteed income. This content contains affiliate links.","This content contains affiliate links.","REJECTED"),("Customer says this works. This content contains affiliate links.","This content contains affiliate links.","REJECTED")])
def test_deterministic_compliance_decisions(db_session,body,disclosure,expected): assert ContentEvaluator(db_session).evaluate(seed(db_session,body=body,disclosure=disclosure).id).decision==expected

def test_unknown_and_ungrounded_claims_reject(db_session):
    artifact=seed(db_session,claims=[{"text":"unknown","source_evidence_ids":["missing"]},{"text":"unsupported","source_evidence_ids":[]}]); result=ContentEvaluator(db_session).evaluate(artifact.id); row=db_session.get(ContentEvaluation,result.evaluation_id)
    assert result.decision=="REJECTED" and "UNKNOWN_EVIDENCE" in row.compliance_flags and "UNGROUNDED_CLAIM" in row.compliance_flags

def test_versions_create_historical_evaluations_and_state_errors(db_session):
    artifact=seed(db_session); evaluator=ContentEvaluator(db_session); a=evaluator.evaluate(artifact.id); b=evaluator.evaluate(artifact.id,evaluator_version="content-evaluator-v2"); c=evaluator.evaluate(artifact.id,policy_version="policy-v2")
    assert len({a.evaluation_id,b.evaluation_id,c.evaluation_id})==3
    artifact.status="OTHER"; db_session.commit()
    with pytest.raises(ValueError,match="not GENERATED"): evaluator.evaluate(artifact.id,evaluator_version="v3")
    with pytest.raises(ValueError,match="not found"): evaluator.evaluate("missing")
