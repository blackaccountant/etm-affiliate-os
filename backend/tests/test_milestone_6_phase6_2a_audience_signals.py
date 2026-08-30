from datetime import datetime, timezone
import pytest
from app.audience.contracts import AudienceSignalError
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate
from app.models.audience import AudienceSignal, AudienceSignalEvidence

def evidence(db, subject_id=None, external="x"):
    foundation=AudienceFoundationService(db); obs=foundation.ingest_observation(research_run_id=None, subject_id=subject_id, source_namespace="first-party", source_type="FIRST_PARTY_WEB", external_observation_id=external, source_reference="ref", observed_at=datetime(2026,1,1,tzinfo=timezone.utc), normalized_fact={"event":"pricing"})
    return foundation.record_evidence(observation_id=obs.id, source_reference=external, normalized_representation={"event":"pricing"}, content_fingerprint=(external*64)[:64])
def candidate(ids, **overrides):
    value=dict(signal_type="INTENT", topic="Managed Hosting", topic_label="Managed hosting", intent_stage="PRICING", strength=70, confidence=80, evidence_ids=ids, ruleset_version="audience-signals-v1", rationale="Observed pricing interaction.", observed_purchase=False); value.update(overrides); return SignalCandidate(**value)
def test_idempotency_order_and_lineage(db_session):
    subject=AudienceFoundationService(db_session).create_subject("PERSON"); a=evidence(db_session,subject.id,"a"); b=evidence(db_session,subject.id,"b"); service=AudienceSignalService(db_session)
    first=service.persist(candidate([a.id,b.id]),subject_id=subject.id); second=service.persist(candidate([b.id,a.id]),subject_id=subject.id)
    assert first.id==second.id and db_session.query(AudienceSignalEvidence).count()==2
def test_validation_and_subjectless_business_need(db_session):
    item=evidence(db_session,None,"c"); service=AudienceSignalService(db_session)
    signal=service.persist(candidate([item.id], signal_type="BUSINESS_NEED", intent_stage=None, topic="CRM replacement", topic_label="CRM replacement", confidence=60),subject_id=None)
    assert signal.subject_id is None
    with pytest.raises(AudienceSignalError, match="purchase requires") : service.persist(candidate([item.id], signal_type="PURCHASE", intent_stage=None, confidence=60), subject_id=None)
def test_bounds_sensitive_conflict_and_supersession(db_session):
    subject=AudienceFoundationService(db_session).create_subject("ORGANIZATION"); item=evidence(db_session,subject.id,"d"); service=AudienceSignalService(db_session); first=service.persist(candidate([item.id],confidence=80),subject_id=subject.id)
    second=service.persist(candidate([item.id],ruleset_version="audience-signals-v2", supersedes_signal_id=first.id),subject_id=subject.id)
    assert second.id != first.id and second.supersedes_signal_id == first.id
    with pytest.raises(AudienceSignalError): service.persist(candidate([item.id],topic="religion", confidence=80),subject_id=subject.id)
    with pytest.raises(AudienceSignalError): service.persist(candidate([item.id],strength=101,confidence=80),subject_id=subject.id)

@pytest.mark.parametrize("kind,stage,observed", [("PROBLEM",None,False),("INTEREST",None,False),("INTENT","RESEARCH",False),("INTENT","COMPARE",False),("INTENT","EVALUATE",False),("INTENT","PRICING",False),("INTENT","PURCHASE_REQUEST",False),("PURCHASE",None,True),("ENGAGEMENT",None,False)])
def test_approved_taxonomy_and_intent_stages(db_session, kind, stage, observed):
    subject=AudienceFoundationService(db_session).create_subject("PERSON"); item=evidence(db_session,subject.id,kind+str(stage)); signal=AudienceSignalService(db_session).persist(candidate([item.id],signal_type=kind,intent_stage=stage,observed_purchase=observed),subject_id=subject.id)
    assert signal.signal_type == kind and signal.intent_stage == stage

@pytest.mark.parametrize("topic", ["religion", "race ethnicity", "political affiliation", "health condition", "sexual orientation"])
def test_sensitive_topics_reject_without_persistence(db_session, topic):
    item=evidence(db_session,None,topic[:1]); service=AudienceSignalService(db_session)
    with pytest.raises(AudienceSignalError) as error: service.persist(candidate([item.id],topic=topic,topic_label=topic,confidence=60),subject_id=None)
    assert error.value.category == "SENSITIVE_SIGNAL_BLOCKED" and db_session.query(AudienceSignal).count() == 0

def test_lineage_bounds_versions_metadata_and_empty_success(db_session):
    foundation=AudienceFoundationService(db_session); person=foundation.create_subject("PERSON"); org=foundation.create_subject("ORGANIZATION"); linked=evidence(db_session,person.id,"l"); other=evidence(db_session,org.id,"o"); anonymous=evidence(db_session,None,"n"); service=AudienceSignalService(db_session)
    assert service.persist_many([],subject_id=None) == []
    with pytest.raises(AudienceSignalError): service.persist(candidate([linked.id,other.id]),subject_id=person.id)
    with pytest.raises(AudienceSignalError): service.persist(candidate([anonymous.id]),subject_id=person.id)
    with pytest.raises(AudienceSignalError): service.persist(candidate([linked.id]),subject_id=None)
    with pytest.raises(AudienceSignalError): service.persist(candidate([linked.id],signal_type="INTEREST",intent_stage="PRICING"),subject_id=person.id)
    with pytest.raises(AudienceSignalError): service.persist(candidate([linked.id],confidence=101),subject_id=person.id)
    with pytest.raises(AudienceSignalError): service.persist(candidate([linked.id],ruleset_version=" "),subject_id=person.id)
    signal=service.persist(candidate([linked.id],strength=0,confidence=0,model_version=None,metadata_json={"source":"fixture"}),subject_id=person.id); assert signal.model_version is None and signal.strength == 0
