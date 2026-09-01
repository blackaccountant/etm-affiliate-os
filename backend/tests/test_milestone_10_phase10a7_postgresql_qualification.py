"""Guarded real-PostgreSQL qualification for M10A7 adjustment authority."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
from uuid import uuid4
import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_financial_adjustment import AffiliateFinancialAdjustment
from app.services.affiliate_financial_adjustment_service import AffiliateFinancialAdjustmentService
from app.affiliate_financial.adjustment_contracts import AffiliateFinancialAdjustmentConflict

DATABASE="etm_g5_m10a7_qualification"; REVISION="e7f8a9b0c1d2"
raw=os.getenv("ETM_G5_DATABASE_URL")
if not raw: pytest.skip("requires guarded ETM_G5_DATABASE_URL",allow_module_level=True)
url=make_url(raw)
if not (url.drivername.startswith("postgresql") and url.host=="127.0.0.1" and url.port==5432 and url.database==DATABASE): raise RuntimeError("M10A7 requires dedicated qualification database")
engine=create_engine(url.render_as_string(hide_password=False),pool_pre_ping=True); Session=sessionmaker(bind=engine,expire_on_commit=False)

@pytest.fixture(scope="module",autouse=True)
def guarded_schema():
 with engine.connect() as c:
  assert c.execute(text("SELECT current_database()")).scalar_one()==DATABASE
  assert MigrationContext.configure(c).get_current_revision()==REVISION
 yield; engine.dispose()

def foundation():
 db=Session(); token=uuid4().hex
 try:
  p=Product(name=token,website=f"https://{token}.invalid",category="test",affiliate_program="yes",commission_type="percentage",commission_value="10",affiliate_score=1,grade="A",confidence=1,summary="",recommendation="",status="active");db.add(p);db.flush()
  program=AffiliateProgram(product_id=p.id,program_name=token,commission_type="percentage",commission_value="10",status="active");db.add(program);db.flush()
  conversion=AffiliateConversion(affiliate_program_id=program.id,external_conversion_id=token,sale_amount=Decimal("100.00"),currency="USD",conversion_status="approved",commission_amount=Decimal("10.00"));db.add(conversion);db.flush()
  earning=AffiliateEarning(conversion_id=conversion.id,affiliate_program_id=program.id,gross_amount=Decimal("100.00"),commission_rate=Decimal("10.0000"),commission_amount=Decimal("10.00"),currency="USD",status="approved");db.add(earning);db.commit();return earning.id,program.id,conversion.id
 finally: db.close()

def call(ids,digest,amount=Decimal("-2.00"),kind="REVERSAL"):
 db=Session()
 try: return AffiliateFinancialAdjustmentService(db).reconcile(earning_id=ids[0],program_id=ids[1],conversion_id=ids[2],adjustment_type=kind,adjustment_amount=amount,currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a7.adjustment",source_event_digest=digest)
 finally: db.close()

def test_schema_replay_decimal_utc_constraints_and_append_only():
 ids=foundation(); digest="a"*64; one=call(ids,digest); two=call(ids,digest)
 assert one.id==two.id and one.adjustment_amount==Decimal("-2.00")
 with pytest.raises(AffiliateFinancialAdjustmentConflict): call(ids,digest,Decimal("-1.00"))
 with pytest.raises(ValueError): call(ids,"b"*64,Decimal("0"))
 with pytest.raises(ValueError): call(ids,"c"*64,Decimal("-1.00"),"RESTORATION")
 db=Session()
 try:
  with pytest.raises(ValueError): AffiliateFinancialAdjustmentService(db).reconcile(earning_id=ids[0],program_id=ids[1],conversion_id=ids[2],adjustment_type="REVERSAL",adjustment_amount=Decimal("-1.00"),currency="EUR",effective_at=datetime.now(timezone.utc),source_namespace="m10a7.adjustment",source_event_digest="d"*64)
 finally: db.close()
 db=Session()
 try:
  fresh=db.get(AffiliateFinancialAdjustment,one.id); assert fresh.recorded_at.tzinfo is not None and fresh.recorded_at.utcoffset()==timezone.utc.utcoffset(fresh.recorded_at)
 finally: db.close()
 with engine.begin() as c:
  with pytest.raises(DBAPIError): c.execute(text("UPDATE affiliate_financial_adjustments SET adjustment_amount=-1 WHERE id=:id"),{"id":one.id})
  with pytest.raises(DBAPIError): c.execute(text("DELETE FROM affiliate_financial_adjustments WHERE id=:id"),{"id":one.id})
 db=Session()
 try: assert db.get(AffiliateFinancialAdjustment,one.id).adjustment_amount==Decimal("-2.00")
 finally: db.close()

def test_cumulative_limit_and_real_concurrent_identity_reconciliation():
 ids=foundation(); call(ids,"e"*64,Decimal("-6.00")); call(ids,"f"*64,Decimal("-4.00"))
 with pytest.raises(ValueError): call(ids,"1"*64,Decimal("-0.01"))
 concurrent=foundation()
 with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:call(concurrent,"2"*64,Decimal("-1.00")).id,range(2)))
 assert len(set(results))==1
 db=Session()
 try: assert db.query(AffiliateFinancialAdjustment).filter_by(affiliate_earning_id=concurrent[0]).count()==1
 finally: db.close()

def test_injected_commit_failure_rolls_back():
 ids=foundation(); db=Session()
 try:
  service=AffiliateFinancialAdjustmentService(db)
  def fail(): raise RuntimeError("injected")
  service.db.commit=fail
  with pytest.raises(RuntimeError,match="injected"):
   service.reconcile(earning_id=ids[0],program_id=ids[1],conversion_id=ids[2],adjustment_type="REVERSAL",adjustment_amount=Decimal("-1.00"),currency="USD",effective_at=datetime.now(timezone.utc),source_namespace="m10a7.adjustment",source_event_digest="3"*64)
 finally: db.close()
 db=Session()
 try: assert db.query(AffiliateFinancialAdjustment).filter_by(affiliate_earning_id=ids[0]).count()==0
 finally: db.close()
