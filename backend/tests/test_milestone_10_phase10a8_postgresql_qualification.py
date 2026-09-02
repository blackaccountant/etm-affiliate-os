"""Guarded PostgreSQL qualification boundary for read-only M10A8 projection."""
import os
import json
from pathlib import Path
import pytest
import requests
import httpx
from dataclasses import asdict
from decimal import Decimal
from datetime import datetime,timezone
from uuid import uuid4
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.services.attribution_net_realized_revenue_projection_service import AttributionNetRealizedRevenueProjectionService
from app.attribution.net_realized_revenue_projection_contracts import NET_REALIZED_REVENUE_PROJECTION_SEMANTICS, NetRealizedRevenueProjectionRequest
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_redirect_bridge_service import AttributionRedirectBridgeService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.affiliate_financial_adjustment_service import AffiliateFinancialAdjustmentService
from app.services.affiliate_payout_service import AffiliatePayoutService
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.publishing_queue import PublishingQueue
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_financial_adjustment import AffiliateFinancialAdjustment
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution import AttributionClick, AttributionContext, AttributionFact, AttributionPublication
from app.models.discovery import DiscoveryRun, DiscoveryCandidate
from app.models.content_brief import ContentBrief
from app.models.content_generation_run import ContentGenerationRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.content_evaluation import ContentEvaluation
from app.models.distribution_run import DistributionRun
from app.services.distribution_run_service import DistributionRunService
from app.distribution.contracts import CreateDistributionRunRequest
from sqlalchemy.orm import sessionmaker

ROLE=os.getenv("ETM_G5_M10A8_DB_ROLE")
_ALLOWED={"clean":{"etm_g5_m10a8_qualification_clean"},"negative":{"etm_g5_m10a8_negative_01","etm_g5_m10a8_negative_02"}}
raw=os.getenv("ETM_G5_DATABASE_URL")
if not raw: pytest.skip("requires guarded ETM_G5_DATABASE_URL",allow_module_level=True)
url=make_url(raw)
DATABASE=url.database
if ROLE not in _ALLOWED or not (url.drivername.startswith("postgresql") and url.host=="127.0.0.1" and url.port==5432 and DATABASE in _ALLOWED[ROLE]): raise RuntimeError(f"M10A8 role/database mismatch: role={ROLE!r}, database={DATABASE!r}, allowed={sorted(_ALLOWED.get(ROLE,()))}")
def require_negative_qualification_database():
 if ROLE != "negative": raise RuntimeError("negative-net qualification requires ETM_G5_M10A8_DB_ROLE=negative")

def test_database_head_and_projection_read_only_shape():
 engine=create_engine(url.render_as_string(hide_password=False))
 with engine.connect() as connection:
  assert connection.execute(text("SELECT current_database()")).scalar_one()==DATABASE
  assert MigrationContext.configure(connection).get_current_revision()=="e7f8a9b0c1d2"
 source=__import__("inspect").getsource(AttributionNetRealizedRevenueProjectionService)
 assert all(token not in source for token in (".add(",".delete(",".flush(",".commit(",".rollback("))

def _settled(sale=Decimal("1000.00"), shared_product_id=None, shared_program_id=None, shared_content_asset_id=None, shared_context_id=None, shared_publication_id=None, shared_link_id=None, attribution_click_key=None, currency="USD", earning_status="paid", payout_status="paid", attempt_status="completed", create_attempt=True, create_settlement_link=True, destination_url="https://x.invalid", customer_reference=None, metadata_json=None, create_click=False):
 engine=create_engine(url.render_as_string(hide_password=False)); Session=sessionmaker(bind=engine,expire_on_commit=False);db=Session();t=uuid4().hex
 try:
  product=db.get(Product,shared_product_id) if shared_product_id is not None else None
  if product is None: product=Product(name=t,website=f"https://{t}.invalid",category="t",affiliate_program="y",commission_type="percentage",commission_value="10",affiliate_score=1,grade="A",confidence=1,summary="",recommendation="",status="active");db.add(product);db.flush()
  program=db.get(AffiliateProgram,shared_program_id) if shared_program_id is not None else None
  if program is None: program=AffiliateProgram(product_id=product.id,program_name=t,commission_type="percentage",commission_value="10",status="active");db.add(program);db.flush()
  if program.product_id != product.id: raise ValueError("shared program/product identity mismatch")
  asset=db.get(AffiliateContentAsset,shared_content_asset_id) if shared_content_asset_id is not None else None
  if asset is None: asset=AffiliateContentAsset(product_id=product.id,asset_type="article",title=t);db.add(asset);db.flush()
  if asset.product_id != product.id: raise ValueError("shared content/product identity mismatch")
  queue=PublishingQueue(content_asset_id=asset.id,channel=t);db.add(queue);db.flush()
  pub=db.get(AttributionPublication,shared_publication_id) if shared_publication_id is not None else AttributionPublicationService(db).bind_legacy(queue.id)
  ctx=db.get(AttributionContext,shared_context_id) if shared_context_id is not None else AttributionContextService(db).create(affiliate_program_id=program.id,attribution_publication_id=pub.id)
  if ctx is None or ctx.affiliate_program_id != program.id: raise ValueError("shared context/program identity mismatch")
  db.commit();link=db.get(AffiliateLink,shared_link_id) if shared_link_id is not None else AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id,attribution_context_id=ctx.id,name=t,destination_url=destination_url,content_asset_id=asset.id)
  if link is None or link.affiliate_program_id != program.id or link.attribution_context_id != ctx.id: raise ValueError("shared link/program/context identity mismatch")
  if create_click: attribution_click_key=AttributionRedirectBridgeService(db).record(tracking_code=link.tracking_code,event_id=str(uuid4()))["attribution_click"].click_key
  result=AttributionConversionBridgeService(db).record(affiliate_program_id=program.id,affiliate_link_id=link.id,external_conversion_id=t,customer_reference=customer_reference,sale_amount=sale,currency=currency,commission_rate=Decimal("10"),metadata_json=metadata_json,attribution_click_key=attribution_click_key);earning_link=AttributionEarningLinkService(db).reconcile(attribution_fact_id=result['fact'].id);earning=result['earning'];now=datetime.now(timezone.utc);payout=AffiliatePayout(affiliate_program_id=program.id,total_amount=Decimal("999.00"),currency=earning.currency,status=payout_status,paid_at=now if payout_status=="paid" else None,created_at=now,updated_at=now);db.add(payout);db.flush();earning.payout_id=payout.id;earning.status=earning_status
  attempt=None
  if create_attempt: attempt=AffiliatePayoutAttempt(payout_id=payout.id,attempt_number=1,amount=payout.total_amount,currency=payout.currency,status=attempt_status,provider='manual',idempotency_key=t,started_at=now,completed_at=now if attempt_status in {"completed","failed"} else None,created_at=now,updated_at=now);db.add(attempt)
  db.commit();settlement=None
  if create_settlement_link: settlement=AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
  return engine,earning.id,program.id,result['conversion'].id,settlement.id if settlement else None
 finally: db.close()

def _failed_then_completed_retry(sale=Decimal("1000.00"),before_retry=None):
 engine,earning_id,program_id,_,_=_settled(sale,earning_status="pending",payout_status="processing",attempt_status="processing",create_settlement_link=False);Session=sessionmaker(bind=engine,expire_on_commit=False);db=Session()
 try:
  earning=db.get(AffiliateEarning,earning_id);payout_id=earning.payout_id;service=AffiliatePayoutService(db);service.fail_payout(payout_id);failed=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout_id,attempt_number=1).one()
  if before_retry: before_retry(engine,earning_id,program_id,payout_id,failed.id)
  service.retry_payout(payout_id,idempotency_key=uuid4().hex);service.complete_payout(payout_id,payout_reference=uuid4().hex);retry=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout_id,attempt_number=2).one();earning_link=db.query(AttributionEarningLink).filter_by(affiliate_earning_id=earning_id).one();settlement=AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id);return engine,earning_id,program_id,payout_id,failed.id,retry.id,settlement.id
 finally: db.close()

def _distribution_publication(account_reference="account",destination="destination"):
 engine=create_engine(url.render_as_string(hide_password=False));Session=sessionmaker(bind=engine,expire_on_commit=False);db=Session();t=uuid4().hex
 try:
  now=datetime.now(timezone.utc);d=DiscoveryRun(id=t+"d",input_type="URL",input_value=f"https://{t}.invalid",status="COMPLETED",idempotency_key=t+"d",candidate_count=1,verified_count=1,selected_count=1,created_at=now,updated_at=now);db.add(d);db.flush();c=DiscoveryCandidate(id=t+"c",run_id=d.id,source_adapter="test",source_type="test",canonical_domain=f"{t}.invalid",program_identity_key=t+"p",dedupe_key=t+"k",commission_model="UNKNOWN",verification_status="VERIFIED",disposition="SELECTED",created_at=now,updated_at=now);db.add(c);db.flush();b=ContentBrief(id=t+"b",discovery_run_id=d.id,discovery_candidate_id=c.id,content_type="ARTICLE",channel_intent="SEO",objective="proof",call_to_action="CHECK_DETAILS",required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED",key_benefits=[],proof_points=[],target_keywords=[],constraints=[],idempotency_key=t+"b",status="READY",created_at=now,updated_at=now);db.add(b);db.flush();g=ContentGenerationRun(id=t+"g",content_brief_id=b.id,idempotency_key=t+"g",provider="test",model="test",prompt_version="v1",generation_parameters={},status="COMPLETED",attempt_count=1,created_at=now,updated_at=now);db.add(g);db.flush();a=GeneratedContentArtifact(id=t+"a",generation_run_id=g.id,content_brief_id=b.id,content_type="ARTICLE",title="proof",hook="proof",body="proof body",call_to_action="CHECK_DETAILS",affiliate_disclosure="disclosure",claims=[],status="GENERATED",created_at=now,updated_at=now);db.add(a);db.flush();e=ContentEvaluation(id=t+"e",artifact_id=a.id,content_brief_id=b.id,generation_run_id=g.id,factual_grounding_score=100,offer_alignment_score=100,intent_alignment_score=100,clarity_score=100,cta_score=100,compliance_score=100,overall_score=100,decision="APPROVED",approved=True,evaluator_version="v1",policy_version="v1",claim_results=[],compliance_flags=[],unsupported_claims=[],missing_evidence_ids=[],revision_reasons=[],rejection_reasons=[],created_at=now,updated_at=now);db.add(e);db.commit();run=DistributionRunService(db).create(CreateDistributionRunRequest(a.id,e.id,"test",account_reference,destination));pub=AttributionPublicationService(db).bind_distribution(run.id);db.commit();return engine,run.id,pub.id
 finally: db.close()

def test_real_settled_revenue_and_adjustments_batch_one():
    engine, earning, program, conversion, settlement = _settled()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    projection = Session()
    try:
        rows = AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("earning",), "USD"))
        assert next(row for row in rows if row.dimensions == (("earning", earning),)).net_realized_commission == Decimal("100.00")
    finally:
        projection.close()
    writer = Session()
    try:
        for digest, amount, kind in (("a" * 64, Decimal("-20.00"), "REVERSAL"), ("b" * 64, Decimal("-30.00"), "REFUND"), ("c" * 64, Decimal("10.00"), "RESTORATION")):
            AffiliateFinancialAdjustmentService(writer).reconcile(earning_id=earning, program_id=program, conversion_id=conversion, settlement_link_id=settlement, adjustment_type=kind, adjustment_amount=amount, currency="USD", effective_at=datetime.now(timezone.utc), source_namespace="m10a8.test", source_event_digest=digest)
    finally:
        writer.close()
    fresh = Session()
    try:
        rows = AttributionNetRealizedRevenueProjectionService(fresh).project(NetRealizedRevenueProjectionRequest(("earning",), "USD"))
        assert next(row for row in rows if row.dimensions == (("earning", earning),)).net_realized_commission == Decimal("60.00")
    finally:
        fresh.close()
    writer = Session()
    try:
        AffiliateFinancialAdjustmentService(writer).reconcile(earning_id=earning, program_id=program, conversion_id=conversion, settlement_link_id=settlement, adjustment_type="REVERSAL", adjustment_amount=Decimal("-60.00"), currency="USD", effective_at=datetime.now(timezone.utc), source_namespace="m10a8.test", source_event_digest="d" * 64)
    finally:
        writer.close()
    zero = Session()
    try:
        rows = AttributionNetRealizedRevenueProjectionService(zero).project(NetRealizedRevenueProjectionRequest(("earning",), "USD"))
        assert next(row for row in rows if row.dimensions == (("earning", earning),)).net_realized_commission == Decimal("0.00")
    finally:
        zero.close()

def test_adjustment_currency_mismatch_is_rejected_before_projection():
    engine, earning, program, conversion, settlement = _settled(); Session=sessionmaker(bind=engine, expire_on_commit=False); writer=Session()
    try:
        with pytest.raises(ValueError, match="lineage mismatch"):
            AffiliateFinancialAdjustmentService(writer).reconcile(earning_id=earning, program_id=program, conversion_id=conversion, settlement_link_id=settlement, adjustment_type="REVERSAL", adjustment_amount=Decimal("-0.01"), currency="EUR", effective_at=datetime.now(timezone.utc), source_namespace="m10a8.test", source_event_digest=uuid4().hex * 2)
    finally:
        writer.close()

def test_exact_decimal_precision_fresh_session():
    engine, earning, program, conversion, settlement = _settled(Decimal("1001.00")); Session=sessionmaker(bind=engine, expire_on_commit=False); writer=Session()
    try:
        assert writer.get(AffiliateEarning, earning).commission_amount == Decimal("100.10")
        ids=[]
        for amount, kind in ((Decimal("-20.03"), "REVERSAL"), (Decimal("-30.07"), "REFUND"), (Decimal("10.01"), "RESTORATION")):
            ids.append(AffiliateFinancialAdjustmentService(writer).reconcile(earning_id=earning,program_id=program,conversion_id=conversion,settlement_link_id=settlement,adjustment_type=kind,adjustment_amount=amount,currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a8.precision",source_event_digest=uuid4().hex*2).id)
        assert [writer.get(AffiliateFinancialAdjustment,id).adjustment_amount for id in ids] == [Decimal("-20.03"),Decimal("-30.07"),Decimal("10.01")]
    finally: writer.close()
    for _ in range(2):
        reader=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(reader).project(NetRealizedRevenueProjectionRequest(("earning",),"USD"));value=next(row.net_realized_commission for row in rows if row.dimensions==(("earning",earning),));assert value==Decimal("60.01") and isinstance(value,Decimal)
        finally: reader.close()

def test_same_currency_program_aggregation_isolated():
    engine, first, program, _, _ = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine, expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()

    _, second, _, _, _ = _settled(Decimal("399.90"), shared_product_id=product_id, shared_program_id=program)
    for _ in range(2):
        db=Session()
        try:
            service=AttributionNetRealizedRevenueProjectionService(db)
            details=service.project(NetRealizedRevenueProjectionRequest(("earning",),"USD")); values={row.dimensions[0][1]:row.net_realized_commission for row in details}; assert values[first]==Decimal("60.01") and values[second]==Decimal("39.99")
            grouped=service.project(NetRealizedRevenueProjectionRequest(("affiliate_program",),"USD")); total=next(row.net_realized_commission for row in grouped if row.dimensions==(("affiliate_program",program),)); assert total==Decimal("100.00") and isinstance(total,Decimal) and values[first]+values[second]==total
        finally: db.close()

def test_usd_eur_remain_separate_without_fx():
    engine, usd, _, _, _ = _settled(Decimal("600.10"), currency="USD"); _, eur, _, _, _ = _settled(Decimal("400.20"), currency="EUR"); Session=sessionmaker(bind=engine,expire_on_commit=False)
    for _ in range(2):
        db=Session()
        try:
            service=AttributionNetRealizedRevenueProjectionService(db); rows=service.project(NetRealizedRevenueProjectionRequest(("earning",)))
            owned={row.dimensions[0][1]:(row.currency,row.net_realized_commission) for row in rows if row.dimensions[0][1] in {usd,eur}}
            assert owned=={usd:("USD",Decimal("60.01")),eur:("EUR",Decimal("40.02"))}
            assert all(currency in {"USD","EUR"} for currency,_ in owned.values())
            assert Decimal("100.03") not in [value for _,value in owned.values()]
        finally: db.close()

def test_negative_net_corruption_fails_closed_without_mutation():
    require_negative_qualification_database()
    engine, earning, program, _, _ = _settled(); Session=sessionmaker(bind=engine, expire_on_commit=False); digest=uuid4().hex*2; adjustment_id=str(uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT INTO affiliate_financial_adjustments (id,affiliate_earning_id,affiliate_program_id,adjustment_type,adjustment_amount,currency,effective_at,source_namespace,source_event_digest,fingerprint,recorded_at) VALUES (:id,:earning,:program,'REVERSAL',-120.00,'USD',now(),'m10a8.corruption',:digest,:fingerprint,now())"),{"id":adjustment_id,"earning":earning,"program":program,"digest":digest,"fingerprint":"f"*64})
    projection=Session()
    try:
        with pytest.raises(ValueError,match="negative net"):
            AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("earning",),"USD"))
    finally: projection.close()
    db=Session()
    try:
        assert db.get(AffiliateEarning,earning).commission_amount==Decimal("100.00")
        assert db.get(AffiliateFinancialAdjustment,adjustment_id).adjustment_amount==Decimal("-120.00")
    finally: db.close()

def test_core_settlement_ineligibility_requires_m10a5_link():
    engine, control, program, _, _ = _settled(); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session(); token=uuid4().hex
    try:
        pending_conversion=AffiliateConversion(affiliate_program_id=program,external_conversion_id=token,sale_amount=Decimal("100.00"),currency="USD",conversion_status="approved",commission_amount=Decimal("100.00")); db.add(pending_conversion); db.flush()
        pending=AffiliateEarning(conversion_id=pending_conversion.id,affiliate_program_id=program,gross_amount=Decimal("100.00"),commission_rate=Decimal("100.0000"),commission_amount=Decimal("100.00"),currency="USD",status="pending")
        manual_conversion=AffiliateConversion(affiliate_program_id=program,external_conversion_id=token+"m",sale_amount=Decimal("100.00"),currency="USD",conversion_status="approved",commission_amount=Decimal("100.00")); db.add(manual_conversion); db.flush()
        manual=AffiliateEarning(conversion_id=manual_conversion.id,affiliate_program_id=program,gross_amount=Decimal("100.00"),commission_rate=Decimal("100.0000"),commission_amount=Decimal("100.00"),currency="USD",status="paid",payout_reference="manual-looking")
        db.add_all([pending,manual]); db.commit(); pending_id,manual_id=pending.id,manual.id
    finally: db.close()

def test_pending_payout_without_settlement_is_excluded():
    engine, control, program, _, _ = _settled(); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()

def test_processing_payout_attempt_without_settlement_is_excluded():
    engine, control, program, _, _ = _settled(); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()

def test_failed_payout_without_settlement_is_excluded():
    engine, control, program, _, _ = _settled(); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()
    _, failed, _, _, settlement = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program,earning_status="pending",payout_status="failed",create_attempt=False,create_settlement_link=False)
    db=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(db).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}; assert values[control]==Decimal("100.00") and failed not in values and settlement is None
    finally: db.close()
    _, processing, _, _, settlement = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program,earning_status="pending",payout_status="processing",attempt_status="processing",create_attempt=True,create_settlement_link=False)
    db=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(db).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}; assert values[control]==Decimal("100.00") and processing not in values and settlement is None
    finally: db.close()
    _, pending, _, _, settlement = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program,earning_status="pending",payout_status="pending",create_attempt=False,create_settlement_link=False)
    db=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(db).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}; assert values[control]==Decimal("100.00") and pending not in values and settlement is None
    finally: db.close()

def test_failed_attempt_without_settlement_is_excluded():
    engine, control, program, _, _ = _settled(Decimal("1000.00")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()
    _, failed_earning, _, _, settlement = _settled(Decimal("25.00"),shared_product_id=product_id,shared_program_id=program,earning_status="pending",payout_status="failed",attempt_status="failed",create_attempt=True,create_settlement_link=False)
    db=Session()
    try:
        failed_row=db.get(AffiliateEarning,failed_earning); payout=db.get(AffiliatePayout,failed_row.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one()
        assert failed_row.status == "pending" and payout.status == "failed" and attempt.status == "failed" and settlement is None
        initial=(failed_row.status,payout.status,attempt.status,attempt.completed_at)
    finally: db.close()
    db=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(db).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}
        assert values[control] == Decimal("100.00") and failed_earning not in values and sum(values.values()) == Decimal("100.00")
    finally: db.close()
    db=Session()
    try:
        failed_row=db.get(AffiliateEarning,failed_earning); payout=db.get(AffiliatePayout,failed_row.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one()
        assert (failed_row.status,payout.status,attempt.status,attempt.completed_at) == initial
        assert db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=failed_earning).count() == 0
        assert db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).count() == 1
    finally: db.close()

def test_paid_completed_without_settlement_is_excluded():
    engine, control, program, _, _ = _settled(Decimal("1000.00")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program).product_id
    finally: db.close()
    _, no_link_earning, _, _, settlement = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program,earning_status="paid",payout_status="paid",attempt_status="completed",create_attempt=True,create_settlement_link=False)
    db=Session()
    try:
        no_link_row=db.get(AffiliateEarning,no_link_earning); payout=db.get(AffiliatePayout,no_link_row.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one()
        assert no_link_row.status == "paid" and payout.status == "paid" and attempt.status == "completed" and settlement is None
        initial=(no_link_row.status,payout.status,attempt.status,attempt.completed_at)
    finally: db.close()
    db=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(db).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}
        assert values[control] == Decimal("100.00") and no_link_earning not in values and sum(values.values()) == Decimal("100.00")
    finally: db.close()
    db=Session()
    try:
        no_link_row=db.get(AffiliateEarning,no_link_earning); payout=db.get(AffiliatePayout,no_link_row.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one()
        assert (no_link_row.status,payout.status,attempt.status,attempt.completed_at) == initial
        assert db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=no_link_earning).count() == 0
        assert db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).count() == 1
    finally: db.close()

def test_retry_lifecycle_fixture_smoke():
    engine, earning_id, _, payout_id, failed_id, retry_id, settlement_id = _failed_then_completed_retry(); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        failed=db.get(AffiliatePayoutAttempt,failed_id); retry=db.get(AffiliatePayoutAttempt,retry_id); settlement=db.get(AttributionPayoutSettlementLink,settlement_id)
        assert failed.status == "failed" and retry.status == "completed" and failed.payout_id == retry.payout_id == payout_id
        assert failed.id != retry.id and failed.attempt_number == 1 and retry.attempt_number == 2
        assert settlement.affiliate_earning_id == earning_id and settlement.affiliate_payout_id == payout_id and settlement.affiliate_payout_attempt_id == retry.id
    finally: db.close()

def test_failed_retry_success_is_realized_once_after_settlement():
    observed={}
    def before_retry(engine, earning_id, program_id, payout_id, failed_id):
        Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
        try:
            failed=db.get(AffiliatePayoutAttempt,failed_id); payout=db.get(AffiliatePayout,payout_id); earning=db.get(AffiliateEarning,earning_id)
            observed["pre_state"]=(earning.status,payout.status,failed.status,failed.completed_at)
        finally: db.close()
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program_id]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}
            assert earning_id not in values and sum(values.values(),Decimal("0.00")) == Decimal("0.00")
        finally: projection.close()
        db=Session()
        try:
            failed=db.get(AffiliatePayoutAttempt,failed_id); payout=db.get(AffiliatePayout,payout_id); earning=db.get(AffiliateEarning,earning_id)
            assert (earning.status,payout.status,failed.status,failed.completed_at) == observed["pre_state"]
            assert db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).count() == 0
        finally: db.close()
    engine, earning_id, program_id, payout_id, failed_id, retry_id, settlement_id = _failed_then_completed_retry(Decimal("1000.00"),before_retry=before_retry); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        failed=db.get(AffiliatePayoutAttempt,failed_id); retry=db.get(AffiliatePayoutAttempt,retry_id); payout=db.get(AffiliatePayout,payout_id); earning=db.get(AffiliateEarning,earning_id); settlement=db.get(AttributionPayoutSettlementLink,settlement_id)
        final_state=(earning.status,payout.status,failed.status,retry.status,failed.completed_at,retry.completed_at)
        assert failed.payout_id == retry.payout_id == payout_id and failed.id != retry.id and failed.attempt_number == 1 and retry.attempt_number == 2
        assert failed.status == "failed" and retry.status == "completed" and earning.status == "paid" and payout.status == "paid"
        assert settlement.affiliate_payout_attempt_id == retry_id and db.query(AttributionPayoutSettlementLink).filter_by(affiliate_payout_attempt_id=failed_id).count() == 0
    finally: db.close()

    projection=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("affiliate_program","earning"),"USD")); own=[r for r in rows if r.dimensions[0][1]==program_id]; values={r.dimensions[1][1]:r.net_realized_commission for r in own}
        assert values == {earning_id:Decimal("100.00")} and sum(values.values()) == Decimal("100.00")
    finally: projection.close()
    db=Session()
    try:
        failed=db.get(AffiliatePayoutAttempt,failed_id); retry=db.get(AffiliatePayoutAttempt,retry_id); payout=db.get(AffiliatePayout,payout_id); earning=db.get(AffiliateEarning,earning_id)
        assert (earning.status,payout.status,failed.status,retry.status,failed.completed_at,retry.completed_at) == final_state
        assert db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout_id).count() == 2
    finally: db.close()

def test_affiliate_program_grouping_is_exact_and_nonduplicating():
    engine, earning_a, program_id, _, settlement_a = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_id=db.get(AffiliateProgram,program_id).product_id
    finally: db.close()
    _, earning_b, shared_program, _, settlement_b = _settled(Decimal("399.90"),shared_product_id=product_id,shared_program_id=program_id)
    assert shared_program == program_id and settlement_a is not None and settlement_b is not None
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a),state(earning_b))
    finally: db.close()
    def bucket():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("affiliate_program",),"USD")); own=[row for row in rows if row.dimensions == (("affiliate_program",program_id),)]
            assert len(own) == 1
            row=own[0]; assert row.currency == "USD" and row.net_realized_commission == Decimal("100.00") and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS
            return row
        finally: projection.close()
    first=bucket(); second=bucket(); assert first == second
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a),state(earning_b)) == initial
    finally: db.close()

def test_product_grouping_is_exact_and_separates_products():
    engine, earning_a1, program_a1, _, settlement_a1 = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try: product_a=db.get(AffiliateProgram,program_a1).product_id
    finally: db.close()
    _, earning_a2, program_a2, _, settlement_a2 = _settled(Decimal("399.90"),shared_product_id=product_a)
    _, earning_b, program_b, _, settlement_b = _settled(Decimal("250.00"))
    db=Session()
    try:
        product_b=db.get(AffiliateProgram,program_b).product_id
        assert product_b != product_a and db.get(AffiliateProgram,program_a1).product_id == product_a and db.get(AffiliateProgram,program_a2).product_id == product_a and db.get(AffiliateProgram,program_b).product_id == product_b
        assert settlement_a1 is not None and settlement_a2 is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a1),state(earning_a2),state(earning_b))
    finally: db.close()
    def buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("product",),"USD")); own=[row for row in rows if row.dimensions in ((('product',product_a),),(('product',product_b),))]
            assert len([row for row in own if row.dimensions == (("product",product_a),)]) == 1 and len([row for row in own if row.dimensions == (("product",product_b),)]) == 1
            values={row.dimensions[0][1]:row.net_realized_commission for row in own}; assert values == {product_a:Decimal("100.00"),product_b:Decimal("25.00")} and all(row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=buckets(); second=buckets(); assert first == second
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a1),state(earning_a2),state(earning_b)) == initial
    finally: db.close()

def test_content_asset_grouping_is_exact_and_separates_assets():
    engine, earning_a1, program_id, conversion_a1, settlement_a1 = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        program=db.get(AffiliateProgram,program_id); product_id=program.product_id; content_a=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_a1).affiliate_link_id).content_asset_id
    finally: db.close()
    _, earning_a2, shared_program, conversion_a2, settlement_a2 = _settled(Decimal("399.90"),shared_product_id=product_id,shared_program_id=program_id,shared_content_asset_id=content_a)
    _, earning_b, _, conversion_b, settlement_b = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program_id)
    db=Session()
    try:
        link_a1=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_a1).affiliate_link_id); link_a2=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_a2).affiliate_link_id); link_b=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_b).affiliate_link_id); content_b=link_b.content_asset_id
        assert shared_program == program_id and link_a1.content_asset_id == link_a2.content_asset_id == content_a and content_b != content_a and settlement_a1 is not None and settlement_a2 is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a1),state(earning_a2),state(earning_b))
    finally: db.close()
    def buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("content_asset",),"USD")); own=[row for row in rows if row.dimensions in ((('content_asset',content_a),),(('content_asset',content_b),))]
            values={row.dimensions[0][1]:row.net_realized_commission for row in own}; assert len(own) == 2 and values == {content_a:Decimal("100.00"),content_b:Decimal("25.00")} and all(row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=buckets(); second=buckets(); assert first == second
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a1),state(earning_a2),state(earning_b)) == initial
    finally: db.close()

def test_affiliate_link_grouping_keeps_shared_content_links_distinct():
    engine, earning_a, program_id, conversion_a, settlement_a = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        product_id=db.get(AffiliateProgram,program_id).product_id; link_a=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_a).affiliate_link_id); content_id=link_a.content_asset_id
    finally: db.close()
    _, earning_b, shared_program, conversion_b, settlement_b = _settled(Decimal("399.90"),shared_product_id=product_id,shared_program_id=program_id,shared_content_asset_id=content_id)
    db=Session()
    try:
        link_b=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_b).affiliate_link_id); assert shared_program == program_id and link_a.content_asset_id == link_b.content_asset_id == content_id and link_a.id != link_b.id and settlement_a is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a),state(earning_b))
    finally: db.close()
    def link_buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("affiliate_link",),"USD")); own=[row for row in rows if row.dimensions in ((('affiliate_link',link_a.id),),(('affiliate_link',link_b.id),))]; values={row.dimensions[0][1]:row.net_realized_commission for row in own}
            assert len(own) == 2 and values == {link_a.id:Decimal("60.01"),link_b.id:Decimal("39.99")} and all(row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=link_buckets(); second=link_buckets(); assert first == second
    projection=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("content_asset",),"USD")); own=[row for row in rows if row.dimensions == (("content_asset",content_id),)]; assert len(own) == 1 and own[0].net_realized_commission == Decimal("100.00")
    finally: projection.close()
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a),state(earning_b)) == initial
    finally: db.close()

def test_attribution_context_grouping_uses_persisted_fact_contexts():
    engine, earning_a1, program_id, conversion_a1, settlement_a1 = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        product_id=db.get(AffiliateProgram,program_id).product_id; fact_a1=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a1).one().attribution_fact_id); context_a=fact_a1.attribution_context_id
    finally: db.close()
    _, earning_a2, shared_program, conversion_a2, settlement_a2 = _settled(Decimal("399.90"),shared_product_id=product_id,shared_program_id=program_id,shared_context_id=context_a)
    _, earning_b, _, conversion_b, settlement_b = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program_id)
    db=Session()
    try:
        fact_a2=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a2).one().attribution_fact_id); fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id); context_b=fact_b.attribution_context_id
        assert shared_program == program_id and fact_a1.attribution_context_id == fact_a2.attribution_context_id == context_a and context_b != context_a and settlement_a1 is not None and settlement_a2 is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a1),state(earning_a2),state(earning_b))
    finally: db.close()
    def buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("attribution_context",),"USD")); own=[row for row in rows if row.dimensions in ((('attribution_context',context_a),),(('attribution_context',context_b),))]; values={row.dimensions[0][1]:row.net_realized_commission for row in own}
            assert len(own) == 2 and values == {context_a:Decimal("100.00"),context_b:Decimal("25.00")} and all(row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=buckets(); second=buckets(); assert first == second
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a1),state(earning_a2),state(earning_b)) == initial
    finally: db.close()

def test_attribution_publication_grouping_merges_distinct_contexts():
    engine, earning_a1, program_id, conversion_a1, settlement_a1 = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        product_id=db.get(AffiliateProgram,program_id).product_id; fact_a1=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a1).one().attribution_fact_id); context_a1=db.get(AttributionContext,fact_a1.attribution_context_id); publication_a=context_a1.attribution_publication_id
    finally: db.close()
    _, earning_a2, program_a2, conversion_a2, settlement_a2 = _settled(Decimal("399.90"),shared_product_id=product_id,shared_publication_id=publication_a)
    _, earning_b, _, conversion_b, settlement_b = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program_id)
    db=Session()
    try:
        fact_a2=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a2).one().attribution_fact_id); context_a2=db.get(AttributionContext,fact_a2.attribution_context_id); fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id); context_b=db.get(AttributionContext,fact_b.attribution_context_id); publication_b=context_b.attribution_publication_id
        assert program_a2 != program_id and context_a1.id != context_a2.id and context_a1.attribution_publication_id == context_a2.attribution_publication_id == publication_a and publication_b != publication_a and settlement_a1 is not None and settlement_a2 is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a1),state(earning_a2),state(earning_b))
    finally: db.close()
    def publication_buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("attribution_publication",),"USD")); own=[row for row in rows if row.dimensions in ((('attribution_publication',publication_a),),(('attribution_publication',publication_b),))]; values={row.dimensions[0][1]:row.net_realized_commission for row in own}
            assert len(own) == 2 and values == {publication_a:Decimal("100.00"),publication_b:Decimal("25.00")} and all(row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=publication_buckets(); second=publication_buckets(); assert first == second
    projection=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("attribution_context",),"USD")); own={row.dimensions[0][1]:row.net_realized_commission for row in rows if row.dimensions[0][1] in {context_a1.id,context_a2.id}}; assert own == {context_a1.id:Decimal("60.01"),context_a2.id:Decimal("39.99")}
    finally: projection.close()
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a1),state(earning_a2),state(earning_b)) == initial
    finally: db.close()

def test_publishing_authority_groups_raw_legacy_queue_ids():
    engine, earning_a1, program_id, conversion_a1, settlement_a1 = _settled(Decimal("600.10")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        product_id=db.get(AffiliateProgram,program_id).product_id; fact_a1=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a1).one().attribution_fact_id); context_a1=db.get(AttributionContext,fact_a1.attribution_context_id); publication_a=db.get(AttributionPublication,context_a1.attribution_publication_id); queue_a=db.get(PublishingQueue,publication_a.legacy_publishing_queue_id)
    finally: db.close()

    _, earning_a2, program_a2, conversion_a2, settlement_a2 = _settled(Decimal("399.90"),shared_product_id=product_id,shared_publication_id=publication_a.id)
    _, earning_b, _, conversion_b, settlement_b = _settled(Decimal("250.00"),shared_product_id=product_id,shared_program_id=program_id)
    db=Session()
    try:
        fact_a2=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a2).one().attribution_fact_id); context_a2=db.get(AttributionContext,fact_a2.attribution_context_id); fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id); publication_b=db.get(AttributionPublication,db.get(AttributionContext,fact_b.attribution_context_id).attribution_publication_id); queue_b=db.get(PublishingQueue,publication_b.legacy_publishing_queue_id)
        assert isinstance(queue_a.id,int) and queue_a.id > 0 and queue_b.id != queue_a.id and publication_a.legacy_publishing_queue_id == queue_a.id and publication_a.distribution_run_id is None and publication_b.legacy_publishing_queue_id == queue_b.id and publication_b.distribution_run_id is None and context_a1.id != context_a2.id and program_a2 != program_id and settlement_a1 is not None and settlement_a2 is not None and settlement_b is not None
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        initial=(state(earning_a1),state(earning_a2),state(earning_b))
    finally: db.close()
    def buckets():
        projection=Session()
        try:
            rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("publishing_authority",),"USD")); own=[row for row in rows if row.dimensions in ((('publishing_authority',queue_a.id),),(('publishing_authority',queue_b.id),))]; values={row.dimensions[0][1]:row.net_realized_commission for row in own}
            assert len(own) == 2 and values == {queue_a.id:Decimal("100.00"),queue_b.id:Decimal("25.00")} and all(isinstance(row.dimensions[0][1],int) and row.dimensions[0][1] not in {publication_a.id,publication_b.id,queue_a.channel,queue_b.channel} and row.currency == "USD" and row.semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            return tuple(sorted(own,key=lambda row:str(row.dimensions)))
        finally: projection.close()
    first=buckets(); second=buckets(); assert first == second
    db=Session()
    try:
        def state(earning_id):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).one(); settlement=db.query(AttributionPayoutSettlementLink).filter_by(affiliate_earning_id=earning_id).one()
            return (earning.commission_amount,earning.status,payout.status,attempt.status,settlement.id)
        assert (state(earning_a1),state(earning_a2),state(earning_b)) == initial
    finally: db.close()

def test_distribution_run_grouping_preserves_null_publishing_authority():
    engine,run_a,pub_a=_distribution_publication(); Session=sessionmaker(bind=engine,expire_on_commit=False)
    _,a1,p1,c1,s1=_settled(Decimal("600.10"),shared_publication_id=pub_a); db=Session()
    try: product=db.get(AffiliateProgram,p1).product_id
    finally: db.close()
    _,a2,p2,c2,s2=_settled(Decimal("399.90"),shared_product_id=product,shared_publication_id=pub_a); _,run_b,pub_b=_distribution_publication(); _,b,_,c3,s3=_settled(Decimal("250.00"),shared_product_id=product,shared_publication_id=pub_b)
    db=Session()
    try:
        ra=db.get(DistributionRun,run_a); rb=db.get(DistributionRun,run_b); pa=db.get(AttributionPublication,pub_a); pb=db.get(AttributionPublication,pub_b); facts=[db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=x).one().attribution_fact_id) for x in (c1,c2,c3)]; contexts=[db.get(AttributionContext,f.attribution_context_id) for f in facts]
        assert run_a!=run_b and all(isinstance(x,str) and len(x)==36 for x in (run_a,run_b)) and pa.distribution_run_id==run_a and pb.distribution_run_id==run_b and pa.legacy_publishing_queue_id is None and pb.legacy_publishing_queue_id is None and contexts[0].attribution_publication_id==contexts[1].attribution_publication_id==pub_a and contexts[0].id!=contexts[1].id and contexts[2].attribution_publication_id==pub_b and p1!=p2 and all(x is not None for x in (s1,s2,s3))
        initial_runs={ra.id:(ra.status,ra.publish_generation,ra.reconciliation_generation,ra.scheduled_for,ra.external_post_id,ra.external_url,ra.result_metadata,pa.id,pa.distribution_run_id,pa.legacy_publishing_queue_id),rb.id:(rb.status,rb.publish_generation,rb.reconciliation_generation,rb.scheduled_for,rb.external_post_id,rb.external_url,rb.result_metadata,pb.id,pb.distribution_run_id,pb.legacy_publishing_queue_id)}
    finally: db.close()
    def project():
        projection=Session()
        try:
            service=AttributionNetRealizedRevenueProjectionService(projection); rows=service.project(NetRealizedRevenueProjectionRequest(("distribution_run",),"USD")); own=[r for r in rows if r.dimensions in ((('distribution_run',run_a),),(('distribution_run',run_b),))]; assert len(own)==2 and {r.dimensions[0][1]:r.net_realized_commission for r in own}=={run_a:Decimal("100.00"),run_b:Decimal("25.00")} and all(isinstance(r.dimensions[0][1],str) and r.currency=="USD" and r.semantics==NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for r in own)
            multi=service.project(NetRealizedRevenueProjectionRequest(("distribution_run","publishing_authority"),"USD")); da=(("distribution_run",run_a),("publishing_authority",None)); dbb=(("distribution_run",run_b),("publishing_authority",None)); own_multi=[r for r in multi if r.dimensions in (da,dbb)]; assert len(own_multi)==2 and {r.dimensions:r.net_realized_commission for r in own_multi}=={da:Decimal("100.00"),dbb:Decimal("25.00")}; return tuple(own),tuple(own_multi)
        finally: projection.close()
    assert project()==project()
    db=Session()
    try:
        def run_state(run_id):
            run=db.get(DistributionRun,run_id); publication=db.query(AttributionPublication).filter_by(distribution_run_id=run_id).one(); return (run.status,run.publish_generation,run.reconciliation_generation,run.scheduled_for,run.external_post_id,run.external_url,run.result_metadata,publication.id,publication.distribution_run_id,publication.legacy_publishing_queue_id)
        assert {run_a:run_state(run_a),run_b:run_state(run_b)}==initial_runs
    finally: db.close()

def test_attribution_click_grouping_preserves_explicit_and_null_correlation():
    engine, earning_b, program_id, conversion_b, settlement_b = _settled(Decimal("399.90")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        conversion_b_row=db.get(AffiliateConversion,conversion_b); link=db.get(AffiliateLink,conversion_b_row.affiliate_link_id); context=db.get(AttributionContext,link.attribution_context_id); publication_id=context.attribution_publication_id; product_id=db.get(AffiliateProgram,program_id).product_id; fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id)
        assert fact_b.attribution_click_id is None and settlement_b is not None
        redirect=AttributionRedirectBridgeService(db).record(tracking_code=link.tracking_code,event_id=str(uuid4())); click=redirect["attribution_click"]; legacy_click=redirect["legacy_click"]; click_key=click.click_key
        assert click.attribution_context_id==context.id and click.affiliate_link_id==link.id
    finally: db.close()
    _, earning_a, shared_program, conversion_a, settlement_a = _settled(Decimal("600.10"),shared_product_id=product_id,shared_program_id=program_id,shared_content_asset_id=link.content_asset_id,shared_context_id=context.id,shared_publication_id=publication_id,shared_link_id=link.id,attribution_click_key=click_key)
    db=Session()
    try:
        fact_a=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a).one().attribution_fact_id); fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id)
        assert shared_program==program_id and fact_a.attribution_click_id==click.id and fact_b.attribution_click_id is None and settlement_a is not None and click.id != link.id and click.id != legacy_click.id
        initial=(fact_a.attribution_click_id,fact_b.attribution_click_id,link.id,link.attribution_context_id,db.get(AffiliateConversion,conversion_a).affiliate_link_id,db.get(AffiliateConversion,conversion_b).affiliate_link_id)
    finally: db.close()
    def project():
        projection=Session()
        try:
            service=AttributionNetRealizedRevenueProjectionService(projection); rows=service.project(NetRealizedRevenueProjectionRequest(("affiliate_program","attribution_click"),"USD")); explicit=(("affiliate_program",program_id),("attribution_click",click.id)); null=(("affiliate_program",program_id),("attribution_click",None)); own=[row for row in rows if row.dimensions in (explicit,null)]; values={row.dimensions:row.net_realized_commission for row in own}
            assert len(own)==2 and values=={explicit:Decimal("60.01"),null:Decimal("39.99")} and sum(values.values())==Decimal("100.00") and all(row.currency=="USD" and row.semantics==NET_REALIZED_REVENUE_PROJECTION_SEMANTICS for row in own)
            direct=service.project(NetRealizedRevenueProjectionRequest(("attribution_click",),"USD")); clicked=next(row for row in direct if row.dimensions==(("attribution_click",click.id),)); assert clicked.net_realized_commission==Decimal("60.01") and isinstance(clicked.dimensions[0][1],str)
            return tuple(own),clicked
        finally: projection.close()
    assert project()==project()
    db=Session()
    try:
        fact_a=db.get(AttributionFact,fact_a.id); fact_b=db.get(AttributionFact,fact_b.id); assert (fact_a.attribution_click_id,fact_b.attribution_click_id,link.id,link.attribution_context_id,db.get(AffiliateConversion,conversion_a).affiliate_link_id,db.get(AffiliateConversion,conversion_b).affiliate_link_id)==initial
    finally: db.close()

def test_duplicate_projection_dimensions_fail_closed():
    with pytest.raises(ValueError,match="projection dimensions must be unique"):
        NetRealizedRevenueProjectionRequest(("affiliate_program","content_asset","affiliate_program")).normalized()

def test_batch_two_aggregation_and_determinism_matrix():
    raw_dimensions=("content_asset","attribution_click","affiliate_program"); reordered_dimensions=("attribution_click","affiliate_program","content_asset"); canonical=("affiliate_program","attribution_click","content_asset")
    assert NetRealizedRevenueProjectionRequest(raw_dimensions).normalized().dimensions==canonical and NetRealizedRevenueProjectionRequest(reordered_dimensions).normalized().dimensions==canonical
    engine, earning_b, program_a, conversion_b, settlement_b=_settled(Decimal("399.90")); Session=sessionmaker(bind=engine,expire_on_commit=False); db=Session()
    try:
        link_a=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_b).affiliate_link_id); context_a=db.get(AttributionContext,link_a.attribution_context_id); product_a=db.get(AffiliateProgram,program_a).product_id; publication_a=context_a.attribution_publication_id; fact_b=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_b).one().attribution_fact_id); assert fact_b.attribution_click_id is None
        redirected=AttributionRedirectBridgeService(db).record(tracking_code=link_a.tracking_code,event_id=str(uuid4())); click_a=redirected["attribution_click"]
    finally: db.close()
    _, earning_a, _, conversion_a, settlement_a=_settled(Decimal("600.10"),shared_product_id=product_a,shared_program_id=program_a,shared_content_asset_id=link_a.content_asset_id,shared_context_id=context_a.id,shared_publication_id=publication_a,shared_link_id=link_a.id,attribution_click_key=click_a.click_key)
    _, earning_c, program_c, conversion_c, settlement_c=_settled(Decimal("500.00")); _, earning_d, program_d, payout_d, failed_d, retry_d, settlement_d=_failed_then_completed_retry(Decimal("250.00")); _, earning_e, program_e, conversion_e, settlement_e=_settled(Decimal("100.00"),currency="EUR")
    db=Session()
    try:
        fact_c=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_c).one().attribution_fact_id); fact_d=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_earning_id=earning_d).one().attribution_fact_id); fact_e=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_e).one().attribution_fact_id)
        asset_c=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_c).affiliate_link_id).content_asset_id; asset_d=db.get(AffiliateLink,db.get(AffiliateEarning,earning_d).conversion_id and db.get(AffiliateConversion,db.get(AffiliateEarning,earning_d).conversion_id).affiliate_link_id).content_asset_id; asset_e=db.get(AffiliateLink,db.get(AffiliateConversion,conversion_e).affiliate_link_id).content_asset_id
        adjustment=AffiliateFinancialAdjustmentService(db).reconcile(earning_id=earning_c,program_id=program_c,conversion_id=conversion_c,settlement_link_id=settlement_c,adjustment_type="REVERSAL",adjustment_amount=Decimal("-50.00"),currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a8.matrix",source_event_digest=uuid4().hex*2)
        assert fact_c.attribution_click_id is None and fact_d.attribution_click_id is None and fact_e.attribution_click_id is None and db.get(AffiliateEarning,earning_c).commission_amount==Decimal("50.00")
        initial=(fact_b.attribution_click_id,db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a).one().attribution_fact_id).attribution_click_id,db.get(AffiliateFinancialAdjustment,adjustment.id).adjustment_amount,db.get(AffiliatePayoutAttempt,failed_d).status,db.get(AffiliatePayoutAttempt,retry_d).status,db.get(AttributionPayoutSettlementLink,settlement_d).affiliate_payout_attempt_id)
    finally: db.close()
    dimensions_a=(("affiliate_program",program_a),("attribution_click",click_a.id),("content_asset",link_a.content_asset_id)); dimensions_b=(("affiliate_program",program_a),("attribution_click",None),("content_asset",link_a.content_asset_id)); dimensions_c=(("affiliate_program",program_c),("attribution_click",None),("content_asset",asset_c)); dimensions_d=(("affiliate_program",program_d),("attribution_click",None),("content_asset",asset_d)); dimensions_e=(("affiliate_program",program_e),("attribution_click",None),("content_asset",asset_e)); expected={dimensions_a:("USD",Decimal("60.01")),dimensions_b:("USD",Decimal("39.99")),dimensions_c:("USD",Decimal("0.00")),dimensions_d:("USD",Decimal("25.00")),dimensions_e:("EUR",Decimal("10.00"))}
    def project(request):
        projection=Session()
        try: return AttributionNetRealizedRevenueProjectionService(projection).project(request)
        finally: projection.close()
    first=project(NetRealizedRevenueProjectionRequest(raw_dimensions)); second=project(NetRealizedRevenueProjectionRequest(raw_dimensions)); equivalent=project(NetRealizedRevenueProjectionRequest(reordered_dimensions)); assert first==second==equivalent
    own=[row for row in first if row.dimensions in expected]; actual={row.dimensions:(row.currency,row.net_realized_commission) for row in own}; order_key=lambda row:(row.currency,tuple((name,str(value)) for name,value in row.dimensions)); assert len(own)==5 and actual==expected and tuple(first)==tuple(sorted(first,key=order_key)) and own==sorted(own,key=order_key)
    assert sum(amount for currency,amount in actual.values() if currency=="USD")==Decimal("125.00") and sum(amount for currency,amount in actual.values() if currency=="EUR")==Decimal("10.00") and Decimal("135.00") not in [row.net_realized_commission for row in own]
    db=Session()
    try:
        fact_a=db.get(AttributionFact,db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_a).one().attribution_fact_id); fact_b=db.get(AttributionFact,fact_b.id); assert (fact_b.attribution_click_id,fact_a.attribution_click_id,db.get(AffiliateFinancialAdjustment,adjustment.id).adjustment_amount,db.get(AffiliatePayoutAttempt,failed_d).status,db.get(AffiliatePayoutAttempt,retry_d).status,db.get(AttributionPayoutSettlementLink,settlement_d).affiliate_payout_attempt_id)==initial
        assert db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout_d).count()==2 and db.get(AffiliateEarning,earning_c).commission_amount==Decimal("50.00")
    finally: db.close()

def test_real_postgresql_snapshot_isolation_a_b_a_c():
    engine, earning_id, program_id, conversion_id, settlement_id=_settled(Decimal("1000.00")); Session=sessionmaker(bind=engine,expire_on_commit=False); request=NetRealizedRevenueProjectionRequest(("affiliate_program",),"USD"); db=Session()
    try:
        earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); settlement=db.get(AttributionPayoutSettlementLink,settlement_id); attempt=db.get(AffiliatePayoutAttempt,settlement.affiliate_payout_attempt_id)
        assert earning.commission_amount==Decimal("100.00") and earning.currency=="USD" and settlement.affiliate_earning_id==earning_id and db.query(AffiliateFinancialAdjustment).filter_by(affiliate_earning_id=earning_id).count()==0
        durable_before=(earning.commission_amount,earning.currency,payout.id,payout.status,attempt.id,attempt.status,settlement.id,settlement.affiliate_payout_id,settlement.affiliate_payout_attempt_id)
    finally: db.close()
    reader=Session()
    try:
        service=AttributionNetRealizedRevenueProjectionService(reader); rows_a1=service.project(request); amount_a1=next(row.net_realized_commission for row in rows_a1 if row.dimensions==(("affiliate_program",program_id),)); assert amount_a1==Decimal("100.00")
        isolation=reader.execute(text("SHOW transaction_isolation")).scalar_one(); read_only=reader.execute(text("SHOW transaction_read_only")).scalar_one(); reader_pid=reader.execute(text("SELECT pg_backend_pid()")).scalar_one(); assert isolation=="repeatable read" and read_only=="on"
        writer=Session()
        try:
            writer_pid=writer.execute(text("SELECT pg_backend_pid()")).scalar_one(); assert writer_pid!=reader_pid
            adjustment=AffiliateFinancialAdjustmentService(writer).reconcile(earning_id=earning_id,program_id=program_id,conversion_id=conversion_id,settlement_link_id=settlement_id,adjustment_type="REVERSAL",adjustment_amount=Decimal("-20.00"),currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a8.snapshot",source_event_digest=uuid4().hex*2)
            assert adjustment.adjustment_amount==Decimal("-20.00")
        finally: writer.close()
        rows_a2=service.project(request); amount_a2=next(row.net_realized_commission for row in rows_a2 if row.dimensions==(("affiliate_program",program_id),)); reader_pid_after=reader.execute(text("SELECT pg_backend_pid()")).scalar_one(); assert amount_a2==Decimal("100.00") and reader_pid_after==reader_pid
    finally:
        reader.rollback(); reader.close()
    fresh=Session()
    try:
        rows_c=AttributionNetRealizedRevenueProjectionService(fresh).project(request); amount_c=next(row.net_realized_commission for row in rows_c if row.dimensions==(("affiliate_program",program_id),)); assert amount_c==Decimal("80.00")
    finally: fresh.close()
    verify=Session()
    try:
        earning=verify.get(AffiliateEarning,earning_id); payout=verify.get(AffiliatePayout,earning.payout_id); settlement=verify.get(AttributionPayoutSettlementLink,settlement_id); attempt=verify.get(AffiliatePayoutAttempt,settlement.affiliate_payout_attempt_id); stored=verify.get(AffiliateFinancialAdjustment,adjustment.id)
        assert stored.adjustment_amount==Decimal("-20.00") and earning.commission_amount==Decimal("100.00") and Decimal(str(earning.commission_amount))+Decimal(str(stored.adjustment_amount))==Decimal("80.00")
        assert (earning.commission_amount,earning.currency,payout.id,payout.status,attempt.id,attempt.status,settlement.id,settlement.affiliate_payout_id,settlement.affiliate_payout_attempt_id)==durable_before
    finally: verify.close()

def test_postgresql_read_only_transaction_rejects_m10a7_adjustment():
    engine, earning_id, program_id, conversion_id, settlement_id=_settled(Decimal("1000.00")); Session=sessionmaker(bind=engine,expire_on_commit=False); request=NetRealizedRevenueProjectionRequest(("affiliate_program",),"USD"); source_digest=uuid4().hex*2; db=Session()
    try:
        earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); settlement=db.get(AttributionPayoutSettlementLink,settlement_id); attempt=db.get(AffiliatePayoutAttempt,settlement.affiliate_payout_attempt_id)
        assert earning.commission_amount==Decimal("100.00") and earning.currency=="USD" and db.query(AffiliateFinancialAdjustment).filter_by(affiliate_program_id=program_id,source_namespace="m10a8.readonly",source_event_digest=source_digest).count()==0
        durable_before=(earning.commission_amount,earning.currency,payout.id,payout.status,attempt.id,attempt.status,settlement.id,settlement.affiliate_payout_id,settlement.affiliate_payout_attempt_id)
    finally: db.close()
    reader=Session(); error=None
    try:
        rows=AttributionNetRealizedRevenueProjectionService(reader).project(request); assert next(row.net_realized_commission for row in rows if row.dimensions==(("affiliate_program",program_id),))==Decimal("100.00")
        isolation=reader.execute(text("SHOW transaction_isolation")).scalar_one(); read_only=reader.execute(text("SHOW transaction_read_only")).scalar_one(); reader_pid=reader.execute(text("SELECT pg_backend_pid()")).scalar_one(); assert isolation=="repeatable read" and read_only=="on"
        with pytest.raises(Exception) as caught:
            AffiliateFinancialAdjustmentService(reader).reconcile(earning_id=earning_id,program_id=program_id,conversion_id=conversion_id,settlement_link_id=settlement_id,adjustment_type="REVERSAL",adjustment_amount=Decimal("-10.00"),currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a8.readonly",source_event_digest=source_digest)
        error=caught.value; origin=getattr(error,"orig",None); sqlstate=getattr(origin,"pgcode",None) or getattr(origin,"sqlstate",None); assert sqlstate=="25006" and "read-only transaction" in str(error).lower()
    finally:
        reader.rollback(); reader.close()
    verify=Session()
    try:
        earning=verify.get(AffiliateEarning,earning_id); payout=verify.get(AffiliatePayout,earning.payout_id); settlement=verify.get(AttributionPayoutSettlementLink,settlement_id); attempt=verify.get(AffiliatePayoutAttempt,settlement.affiliate_payout_attempt_id)
        assert verify.query(AffiliateFinancialAdjustment).filter_by(affiliate_program_id=program_id,source_namespace="m10a8.readonly",source_event_digest=source_digest).count()==0 and earning.commission_amount==Decimal("100.00")
        assert (earning.commission_amount,earning.currency,payout.id,payout.status,attempt.id,attempt.status,settlement.id,settlement.affiliate_payout_id,settlement.affiliate_payout_attempt_id)==durable_before
    finally: verify.close()
    fresh=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(fresh).project(request); assert next(row.net_realized_commission for row in rows if row.dimensions==(("affiliate_program",program_id),))==Decimal("100.00")
    finally: fresh.close()

def test_durable_no_mutation_and_privacy_sentinel():
    token=uuid4().hex
    sentinel_a=f"https://privacy-sentinel-{token}.invalid"
    sentinel_b=f"PRIVACY_SENTINEL_CUSTOMER_{token}"
    sentinel_c=f"PRIVACY_SENTINEL_METADATA_{token}"
    sentinel_d=f"PRIVACY_SENTINEL_ACCOUNT_{token}"
    sentinel_e=f"PRIVACY_SENTINEL_DESTINATION_{token}"
    engine,run_id,publication_id=_distribution_publication(sentinel_d,sentinel_e)
    _,earning_id,program_id,conversion_id,settlement_id=_settled(Decimal("1000.00"),shared_publication_id=publication_id,destination_url=sentinel_a,customer_reference=sentinel_b,metadata_json=json.dumps({"sentinel":sentinel_c},sort_keys=True),create_click=True)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    try:
        earning=db.get(AffiliateEarning,earning_id); conversion=db.get(AffiliateConversion,conversion_id); link=db.get(AffiliateLink,conversion.affiliate_link_id); context=db.get(AttributionContext,link.attribution_context_id); publication=db.get(AttributionPublication,publication_id); product=db.get(Product,db.get(AffiliateProgram,program_id).product_id); asset=db.get(AffiliateContentAsset,link.content_asset_id); fact=db.query(AttributionFact).filter_by(affiliate_conversion_id=conversion_id).one(); click=db.get(AttributionClick,fact.attribution_click_id); payout=db.get(AffiliatePayout,earning.payout_id); attempt=db.get(AffiliatePayoutAttempt,db.get(AttributionPayoutSettlementLink,settlement_id).affiliate_payout_attempt_id); earning_link=db.query(AttributionEarningLink).filter_by(affiliate_earning_id=earning_id).one(); run=db.get(DistributionRun,run_id)
        assert publication.distribution_run_id==run_id and publication.legacy_publishing_queue_id is None and click is not None and fact.attribution_click_id==click.id
        adjustment=AffiliateFinancialAdjustmentService(db).reconcile(earning_id=earning_id,program_id=program_id,conversion_id=conversion_id,settlement_link_id=settlement_id,adjustment_type="REVERSAL",adjustment_amount=Decimal("-20.00"),currency="USD",effective_at=datetime.now(timezone.utc),source_namespace=f"m10a8.privacy.{token}",source_event_digest=uuid4().hex*2)
        ids={"product":product.id,"program":program_id,"asset":asset.id,"link":link.id,"publication":publication_id,"context":context.id,"click":click.id,"fact":fact.id,"conversion":conversion_id,"earning":earning_id,"payout":payout.id,"attempt":attempt.id,"earning_link":earning_link.id,"settlement":settlement_id,"adjustment":adjustment.id,"run":run_id}
    finally: db.close()
    def fingerprint(session):
        product=session.get(Product,ids["product"]); program=session.get(AffiliateProgram,ids["program"]); asset=session.get(AffiliateContentAsset,ids["asset"]); link=session.get(AffiliateLink,ids["link"]); publication=session.get(AttributionPublication,ids["publication"]); context=session.get(AttributionContext,ids["context"]); click=session.get(AttributionClick,ids["click"]); fact=session.get(AttributionFact,ids["fact"]); conversion=session.get(AffiliateConversion,ids["conversion"]); earning=session.get(AffiliateEarning,ids["earning"]); payout=session.get(AffiliatePayout,ids["payout"]); attempt=session.get(AffiliatePayoutAttempt,ids["attempt"]); earning_link=session.get(AttributionEarningLink,ids["earning_link"]); settlement=session.get(AttributionPayoutSettlementLink,ids["settlement"]); adjustment=session.get(AffiliateFinancialAdjustment,ids["adjustment"]); run=session.get(DistributionRun,ids["run"])
        records=(
            ("Product",product.id,(product.id,product.name,product.website,product.affiliate_url,product.status)),
            ("AffiliateProgram",program.id,(program.id,program.product_id,program.program_name,program.network,program.program_url,program.status)),
            ("AffiliateContentAsset",asset.id,(asset.id,asset.product_id,asset.version,asset.is_active,asset.asset_type,asset.title,asset.published_url,asset.status)),
            ("AffiliateLink",link.id,(link.id,link.affiliate_program_id,link.content_asset_id,link.attribution_context_id,link.name,link.destination_url,link.tracking_code,link.is_active)),
            ("AttributionPublication",publication.id,(publication.id,publication.distribution_run_id,publication.legacy_publishing_queue_id)),
            ("AttributionContext",context.id,(context.id,context.affiliate_program_id,context.attribution_publication_id,context.context_fingerprint)),
            ("AttributionClick",click.id,(click.id,click.click_key,click.attribution_context_id,click.affiliate_link_id,click.source_namespace,click.source_event_key_digest,click.source_fingerprint)),
            ("AttributionFact",fact.id,(fact.id,fact.fact_kind,fact.source_namespace,fact.source_event_key_digest,fact.attribution_publication_id,fact.attribution_context_id,fact.attribution_click_id,fact.affiliate_link_id,fact.affiliate_conversion_id)),
            ("AffiliateConversion",conversion.id,(conversion.id,conversion.affiliate_link_id,conversion.affiliate_program_id,conversion.external_conversion_id,conversion.customer_reference,conversion.sale_amount,conversion.currency,conversion.conversion_status,conversion.commission_rate,conversion.commission_amount,conversion.source,conversion.metadata_json)),
            ("AffiliateEarning",earning.id,(earning.id,earning.conversion_id,earning.affiliate_program_id,earning.gross_amount,earning.commission_rate,earning.commission_amount,earning.currency,earning.status,earning.payout_id,earning.payout_reference)),
            ("AffiliatePayout",payout.id,(payout.id,payout.affiliate_program_id,payout.total_amount,payout.currency,payout.status,payout.payout_reference)),
            ("AffiliatePayoutAttempt",attempt.id,(attempt.id,attempt.payout_id,attempt.attempt_number,attempt.amount,attempt.currency,attempt.status,attempt.provider,attempt.provider_reference,attempt.idempotency_key,attempt.failure_reason)),
            ("AttributionEarningLink",earning_link.id,(earning_link.id,earning_link.attribution_fact_id,earning_link.affiliate_conversion_id,earning_link.affiliate_earning_id,earning_link.source_namespace,earning_link.source_event_key_digest,earning_link.linkage_fingerprint)),
            ("AttributionPayoutSettlementLink",settlement.id,(settlement.id,settlement.attribution_earning_link_id,settlement.affiliate_earning_id,settlement.affiliate_payout_id,settlement.affiliate_payout_attempt_id,settlement.source_namespace,settlement.source_event_key_digest,settlement.linkage_fingerprint)),
            ("AffiliateFinancialAdjustment",adjustment.id,(adjustment.id,adjustment.affiliate_earning_id,adjustment.affiliate_program_id,adjustment.affiliate_conversion_id,adjustment.affiliate_payout_id,adjustment.attribution_payout_settlement_link_id,adjustment.adjustment_type,adjustment.adjustment_amount,adjustment.currency,adjustment.source_namespace,adjustment.source_event_digest,adjustment.fingerprint)),
            ("DistributionRun",run.id,(run.id,run.generated_content_artifact_id,run.content_evaluation_id,run.platform,run.account_reference,run.destination,run.status,run.publish_generation,run.reconciliation_generation,run.idempotency_key,run.payload_fingerprint,run.external_post_id,run.external_url,json.dumps(run.result_metadata,sort_keys=True),run.failure_category,run.error_summary)),
        )
        return tuple(sorted(records,key=lambda record:(record[0],str(record[1]))))
    before_session=Session()
    try: before=fingerprint(before_session)
    finally: before_session.close()
    dimensions=("affiliate_program","product","content_asset","attribution_publication","publishing_authority","distribution_run","affiliate_link","attribution_context","attribution_click","conversion","earning","settlement_link")
    projection=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(dimensions,"USD"))
        expected={"affiliate_program":ids["program"],"product":ids["product"],"content_asset":ids["asset"],"attribution_publication":ids["publication"],"publishing_authority":None,"distribution_run":ids["run"],"affiliate_link":ids["link"],"attribution_context":ids["context"],"attribution_click":ids["click"],"conversion":ids["conversion"],"earning":ids["earning"],"settlement_link":ids["settlement"]}
        matches=[row for row in rows if dict(row.dimensions)==expected]
        assert len(matches)==1 and matches[0].currency=="USD" and matches[0].net_realized_commission==Decimal("80.00") and matches[0].semantics==NET_REALIZED_REVENUE_PROJECTION_SEMANTICS
        serialized_rows=[asdict(row) for row in rows]; assert all(set(row)=={"currency","net_realized_commission","dimensions","semantics"} for row in serialized_rows)
        serialized_projection=json.dumps(serialized_rows,default=str,sort_keys=True)
        assert all(sentinel not in serialized_projection for sentinel in (sentinel_a,sentinel_b,sentinel_c,sentinel_d,sentinel_e))
    finally: projection.close()
    after_session=Session()
    try:
        after=fingerprint(after_session); earning=after_session.get(AffiliateEarning,earning_id); adjustment=after_session.get(AffiliateFinancialAdjustment,ids["adjustment"]); payout=after_session.get(AffiliatePayout,ids["payout"]); attempt=after_session.get(AffiliatePayoutAttempt,ids["attempt"]); settlement=after_session.get(AttributionPayoutSettlementLink,settlement_id); link=after_session.get(AffiliateLink,ids["link"]); conversion=after_session.get(AffiliateConversion,conversion_id); run=after_session.get(DistributionRun,run_id)
        assert after==before and earning.commission_amount==Decimal("100.00") and earning.currency=="USD" and adjustment.adjustment_amount==Decimal("-20.00") and Decimal(str(earning.commission_amount))+Decimal(str(adjustment.adjustment_amount))==Decimal("80.00")
        assert payout.status=="paid" and attempt.status=="completed" and settlement.affiliate_earning_id==earning_id
        assert link.destination_url==sentinel_a and conversion.customer_reference==sentinel_b and sentinel_c in conversion.metadata_json and run.account_reference==sentinel_d and run.destination==sentinel_e
    finally: after_session.close()

def test_zero_external_calls_and_native_currency_isolation(monkeypatch):
    engine,usd_earning,usd_program,_,usd_settlement=_settled(Decimal("1000.00"),currency="USD")
    _,eur_earning,eur_program,_,eur_settlement=_settled(Decimal("400.00"),currency="EUR")
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    try:
        def assert_settled(earning_id,settlement_id,currency,commission):
            earning=db.get(AffiliateEarning,earning_id); payout=db.get(AffiliatePayout,earning.payout_id); settlement=db.get(AttributionPayoutSettlementLink,settlement_id); attempt=db.get(AffiliatePayoutAttempt,settlement.affiliate_payout_attempt_id)
            assert earning.commission_amount==commission and earning.currency==currency and earning.status=="paid" and payout.status=="paid" and payout.currency==currency and attempt.status=="completed" and attempt.currency==currency and settlement.affiliate_earning_id==earning_id and settlement.affiliate_payout_id==payout.id and db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id,status="completed").count()==1
        assert_settled(usd_earning,usd_settlement,"USD",Decimal("100.00")); assert_settled(eur_earning,eur_settlement,"EUR",Decimal("40.00"))
    finally: db.close()
    root=Path(__file__).resolve().parents[1]
    projection_sources="\n".join((root/path).read_text(encoding="utf-8") for path in (
        "app/attribution/net_realized_revenue_projection_contracts.py","app/attribution/realized_revenue_projection_contracts.py","app/services/attribution_net_realized_revenue_projection_service.py","app/repositories/attribution_net_realized_revenue_projection_repository.py","app/repositories/attribution_realized_revenue_projection_repository.py"))
    assert all(token not in projection_sources.lower() for token in ("requests","httpx","aiohttp","urllib.request","provider","adapter","exchange_rate","currency_converter","enrich","browser","scrap","openai","llm"))
    calls={"requests":0,"httpx_sync":0,"httpx_async":0}
    def fail_requests(*args,**kwargs): calls["requests"]+=1; raise AssertionError("requests external HTTP is forbidden during M10A8 projection")
    def fail_httpx_sync(*args,**kwargs): calls["httpx_sync"]+=1; raise AssertionError("httpx synchronous external HTTP is forbidden during M10A8 projection")
    async def fail_httpx_async(*args,**kwargs): calls["httpx_async"]+=1; raise AssertionError("httpx asynchronous external HTTP is forbidden during M10A8 projection")
    monkeypatch.setattr(requests.sessions.Session,"request",fail_requests); monkeypatch.setattr(httpx.Client,"request",fail_httpx_sync); monkeypatch.setattr(httpx.AsyncClient,"request",fail_httpx_async)
    projection=Session()
    try:
        rows=AttributionNetRealizedRevenueProjectionService(projection).project(NetRealizedRevenueProjectionRequest(("affiliate_program",),None))
        usd_row=next(row for row in rows if row.dimensions==(("affiliate_program",usd_program),)); eur_row=next(row for row in rows if row.dimensions==(("affiliate_program",eur_program),))
        assert (usd_row.currency,usd_row.net_realized_commission)==("USD",Decimal("100.00")) and (eur_row.currency,eur_row.net_realized_commission)==("EUR",Decimal("40.00")) and Decimal("140.00") not in {usd_row.net_realized_commission,eur_row.net_realized_commission}
        assert calls=={"requests":0,"httpx_sync":0,"httpx_async":0}
    finally: projection.close()
    verify=Session()
    try:
        for earning_id,settlement_id,currency,commission in ((usd_earning,usd_settlement,"USD",Decimal("100.00")),(eur_earning,eur_settlement,"EUR",Decimal("40.00"))):
            earning=verify.get(AffiliateEarning,earning_id); settlement=verify.get(AttributionPayoutSettlementLink,settlement_id); payout=verify.get(AffiliatePayout,earning.payout_id); assert (earning.commission_amount,earning.currency,payout.status,settlement.affiliate_earning_id)==(commission,currency,"paid",earning_id)
    finally: verify.close()
