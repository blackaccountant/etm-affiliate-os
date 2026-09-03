import os
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.eligible_operating_profit_candidate_set_service import EligibleOperatingProfitCandidateSetService

ROLE, RAW = os.getenv("ETM_G5_M11A4_DB_ROLE"), os.getenv("ETM_G5_M11A4_DATABASE_URL")
if not RAW: pytest.skip("requires guarded M11A4 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != "etm_g5_m11a4_eligible_operating_profit_candidate_set_qualification": raise RuntimeError("M11A4 database guard failed")
def _session(): return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()
def _settled(*, product_id=None, program_id=None, currency="USD"):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id else Product(name=token,website=f"https://{token}.invalid",category="test",affiliate_program="test",commission_type="percentage",commission_value="10",affiliate_score=1,grade="A",confidence=1,summary="",recommendation="",status="active")
        if not product_id: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id else AffiliateProgram(product_id=product.id,program_name=token,commission_type="percentage",commission_value="10",status="active")
        if not program_id: db.add(program); db.flush()
        asset=AffiliateContentAsset(product_id=product.id,asset_type="article",title=token); db.add(asset); db.flush(); queue=PublishingQueue(content_asset_id=asset.id,channel=token); db.add(queue); db.flush()
        publication=AttributionPublicationService(db).bind_legacy(queue.id); context=AttributionContextService(db).create(affiliate_program_id=program.id,attribution_publication_id=publication.id); db.commit()
        link=AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id,attribution_context_id=context.id,name=token,destination_url="https://private.invalid",content_asset_id=asset.id)
        result=AttributionConversionBridgeService(db).record(affiliate_program_id=program.id,affiliate_link_id=link.id,external_conversion_id=token,customer_reference="private",sale_amount=Decimal("1000"),currency=currency,commission_rate=Decimal("10"),metadata_json=json.dumps({"private":token}))
        earning_link=AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id); earning,now=result["earning"],datetime.now(timezone.utc)
        payout=AffiliatePayout(affiliate_program_id=program.id,total_amount=earning.commission_amount,currency=currency,status="paid",paid_at=now,created_at=now,updated_at=now); db.add(payout); db.flush(); earning.payout_id,earning.status=payout.id,"paid"
        db.add(AffiliatePayoutAttempt(payout_id=payout.id,attempt_number=1,amount=payout.total_amount,currency=currency,status="completed",provider="manual",idempotency_key=token,started_at=now,completed_at=now,created_at=now,updated_at=now)); db.commit(); AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"product":product.id,"program":program.id}
    finally: db.close()
def _request(minimum=1, currency="USD"): return EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), currency, OperatingProfitEvidenceEligibilityPolicy("p",minimum,minimum,minimum), datetime(2100,1,1,tzinfo=timezone.utc))
def _ids(rows): return {dict(row.dimensions)["affiliate_program"] for row in rows}
def test_current_head_requires_no_m11a4_migration():
    db=_session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision()=="c3d4e5f6a7b8"
    finally: db.close()
def test_real_m11a3_composition_is_once_read_only_and_network_free(monkeypatch):
    eligible, ineligible = _settled(), _settled()
    db, calls, after = _session(), [], []
    service=EligibleOperatingProfitCandidateSetService(db); real=service._eligibility.project; inside=[False]; engine=db.get_bind()
    def listener(*args):
        if not inside[0]: after.append(args[2])
    event.listen(engine,"before_cursor_execute",listener)
    monkeypatch.setattr(requests.sessions.Session,"request",lambda *a,**k: (_ for _ in ()).throw(AssertionError("network called")))
    monkeypatch.setattr(httpx.Client,"request",lambda *a,**k: (_ for _ in ()).throw(AssertionError("network called")))
    try:
        def wrapped(value):
            calls.append(value); inside[0]=True
            try: return real(value)
            finally: inside[0]=False
        monkeypatch.setattr(service._eligibility,"project",wrapped)
        rows=service.project(_request(1)); assert {eligible["program"],ineligible["program"]}.issubset(_ids(rows)) and len(calls)==1 and after==[]
        with pytest.raises(Exception): db.execute(text("CREATE TABLE m11a4_forbidden_write (id integer)"))
        db.rollback()
    finally:
        event.remove(engine,"before_cursor_execute",listener); db.close()

def test_ineligible_absence_and_a_b_a_c_membership():
    first, second = _settled(), _settled(); _settled(product_id=first["product"],program_id=first["program"])
    request=_request(2); reader=_session()
    try:
        service=EligibleOperatingProfitCandidateSetService(reader); before=_ids(service.project(request)); assert first["program"] in before and second["program"] not in before
        _settled(product_id=second["product"],program_id=second["program"]); assert _ids(service.project(request))==before
    finally: reader.close()
    fresh=_session()
    try: assert _ids(EligibleOperatingProfitCandidateSetService(fresh).project(request)) == before | {second["program"]}
    finally: fresh.close()

def test_native_currency_partition_is_real_and_isolated():
    usd, eur = _settled(), _settled(currency="EUR")
    usd_db = _session()
    try:
        usd_rows = EligibleOperatingProfitCandidateSetService(usd_db).project(_request())
        assert {row.currency for row in usd_rows} == {"USD"} and usd["program"] in _ids(usd_rows)
    finally: usd_db.close()
    eur_db = _session()
    try:
        eur_rows = EligibleOperatingProfitCandidateSetService(eur_db).project(_request(currency="EUR"))
        assert {row.currency for row in eur_rows} == {"EUR"} and eur["program"] in _ids(eur_rows)
    finally: eur_db.close()
