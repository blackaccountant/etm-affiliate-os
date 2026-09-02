import os
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from alembic.runtime.migration import MigrationContext
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.services.affiliate_cost_event_service import AffiliateCostEventService, AffiliateCostEventConflict
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram

ROLE=os.getenv("ETM_G5_M10A9A_DB_ROLE"); raw=os.getenv("ETM_G5_DATABASE_URL")
if not raw: pytest.skip("requires guarded ETM_G5_DATABASE_URL",allow_module_level=True)
url=make_url(raw)
if ROLE!="qualification" or not(url.drivername.startswith("postgresql") and url.host=="127.0.0.1" and url.port==5432 and url.database=="etm_g5_m10a9a_cost_authority_qualification"): raise RuntimeError("M10A9A qualification database guard failed")

def fixture():
    e=create_engine(url.render_as_string(hide_password=False)); S=sessionmaker(bind=e,expire_on_commit=False); s=S(); token=uuid4().hex
    try:
        p=Product(name=token,website=f"https://{token}.invalid",category="test",affiliate_program="test",commission_type="percentage",commission_value="1",affiliate_score=1,grade="A",confidence=1,summary="",recommendation="",status="active");s.add(p);s.flush(); program=AffiliateProgram(product_id=p.id,program_name=token,commission_type="percentage",commission_value="1",status="active");s.add(program);s.commit();return e,program.id
    finally:s.close()
def req(program,key=None,**kw):
    data=dict(amount=Decimal("12.34"),currency="usd",cost_type="provider_fee",allocation_scope="direct",source_namespace="m10a9a.test",source_event_key=key or uuid4().hex,affiliate_program_id=program);data.update(kw);return RecordAffiliateCostEventRequest(**data)
def test_head_persistence_replay_conflict_and_boundaries():
    e,program=fixture(); S=sessionmaker(bind=e,expire_on_commit=False); s=S(); key=uuid4().hex
    try:
        assert MigrationContext.configure(s.connection()).get_current_revision()=="a9b0c1d2e3f4"; service=AffiliateCostEventService(s); first=service.record(req(program,key)); replay=service.record(req(program,key)); assert first.id==replay.id and first.amount==Decimal("12.34") and first.currency=="USD"; assert s.query(AffiliateCostEvent).filter_by(id=first.id).one().affiliate_program_id==program
        with pytest.raises(AffiliateCostEventConflict): service.record(req(program,key,amount=Decimal("13.00")))
        s.rollback(); assert s.get(AffiliateCostEvent,first.id).amount==Decimal("12.34")
        with pytest.raises(ValueError): service.record(req(None,allocation_scope="direct",affiliate_program_id=None))
        with pytest.raises(ValueError): service.record(req(program,allocation_scope="global"))
        shared=service.record(req(None,allocation_scope="shared",affiliate_program_id=None)); global_=service.record(req(None,allocation_scope="global",affiliate_program_id=None)); assert shared.allocation_scope=="shared" and global_.allocation_scope=="global"
    finally:s.close()
def test_postgresql_append_only_and_native_currency_no_auto_costs():
    e,program=fixture(); S=sessionmaker(bind=e,expire_on_commit=False); s=S()
    try:
        service=AffiliateCostEventService(s); usd=service.record(req(program)); eur=service.record(req(program,currency="EUR")); assert usd.currency=="USD" and eur.currency=="EUR" and usd.amount==eur.amount and usd.id!=eur.id
        with pytest.raises(Exception) as update: s.execute(text("UPDATE affiliate_cost_events SET amount=99 WHERE id=:id"),{"id":usd.id})
        assert "append-only" in str(update.value); s.rollback()
        with pytest.raises(Exception) as delete: s.execute(text("DELETE FROM affiliate_cost_events WHERE id=:id"),{"id":usd.id})
        assert "append-only" in str(delete.value); s.rollback()
        assert s.query(AffiliateCostEvent).filter_by(id=usd.id).one().amount==Decimal("12.34")
    finally:s.close()
