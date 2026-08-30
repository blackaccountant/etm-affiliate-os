import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from alembic.runtime.migration import MigrationContext

raw=os.getenv("ETM_G5_DATABASE_URL")
if not raw: pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.",allow_module_level=True)
url=make_url(raw)
if not(url.drivername.startswith("postgresql") and url.host=="127.0.0.1" and url.port==5432 and url.database=="etm_affiliate_os_g5_test"): raise RuntimeError("G5 only")
engine=create_engine(url.render_as_string(hide_password=False))
def row(key, strength=50, confidence=50, kind="INTENT", stage="PRICING"):
 return {"id":key+"000000000000000000000000000000"[:36-len(key)],"key":key.ljust(64,"x")[:64],"strength":strength,"confidence":confidence,"kind":kind,"stage":stage}
def insert(c,r): c.execute(text("INSERT INTO audience_signals (id,signal_type,topic_slug,topic_label,intent_stage,strength,confidence,evidence_set_fingerprint,extraction_key,ruleset_version,observed_at,derived_at,created_at) VALUES (:id,:kind,'hosting','Hosting',:stage,:strength,:confidence,repeat('a',64),:key,'v1',now(),now(),now())"),r)
def test_postgresql_strength_check():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"
  c.rollback()
  tx=c.begin()
  try:
   insert(c,row("zero",0,50)); insert(c,row("hundred",100,50));
   for n,kwargs in enumerate(({"strength":-1},{"strength":101})):
    sp=c.begin_nested()
    with pytest.raises(IntegrityError): insert(c,row("bad"+str(n),**kwargs))
    sp.rollback()
   assert c.execute(text("SELECT count(*) FROM audience_signals WHERE extraction_key IN (:zero, :hundred)"), {"zero": row("zero")["key"], "hundred": row("hundred")["key"]}).scalar_one() == 2
  finally: tx.rollback()

def test_postgresql_confidence_check():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"
  c.rollback(); tx=c.begin()
  try:
   insert(c,row("confidence-zero",50,0)); insert(c,row("confidence-hundred",50,100))
   for n,value in enumerate((-1,101)):
    sp=c.begin_nested()
    with pytest.raises(IntegrityError): insert(c,row("confidence-bad"+str(n),50,value))
    sp.rollback()
  finally: tx.rollback()

def test_non_intent_signal_with_intent_stage_is_rejected_by_postgresql():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"; c.rollback(); tx=c.begin()
  try:
   with pytest.raises(IntegrityError) as error: insert(c,row("problem-stage",50,50,"PROBLEM","RESEARCH"))
   assert "ck_audience_signals_intent_stage" in str(error.value.orig); c.rollback()
   assert c.execute(text("SELECT count(*) FROM audience_signals WHERE extraction_key=:key"),{"key":row("problem-stage")["key"]}).scalar_one()==0
  finally:
   if c.in_transaction(): c.rollback()

def test_intent_signal_with_valid_stage_is_accepted_by_postgresql():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"; c.rollback(); tx=c.begin()
  try:
   value=row("intent-research",50,50,"INTENT","RESEARCH"); insert(c,value)
   stored=c.execute(text("SELECT signal_type,intent_stage FROM audience_signals WHERE extraction_key=:key"),{"key":value["key"]}).one()
   assert tuple(stored)==("INTENT","RESEARCH")
  finally: tx.rollback()

def test_intent_signal_with_null_stage_is_accepted_by_postgresql():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"; c.rollback(); tx=c.begin()
  try:
   value=row("intent-null",50,50,"INTENT",None); insert(c,value)
   assert c.execute(text("SELECT intent_stage FROM audience_signals WHERE extraction_key=:key"),{"key":value["key"]}).scalar_one() is None
  finally: tx.rollback()

def test_extraction_key_is_unique_in_postgresql():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"; c.rollback(); tx=c.begin()
  try:
   first=row("unique-first"); insert(c,first); duplicate=row("unique-second"); duplicate["key"]=first["key"]
   sp=c.begin_nested()
   with pytest.raises(IntegrityError) as error: insert(c,duplicate)
   assert "uq_audience_signals_extraction_key" in str(error.value.orig); sp.rollback()
   assert c.execute(text("SELECT count(*) FROM audience_signals WHERE extraction_key=:key"),{"key":first["key"]}).scalar_one()==1
  finally: tx.rollback()

def test_signal_evidence_pair_is_unique_in_postgresql():
 with engine.connect() as c:
  assert MigrationContext.configure(c).get_current_revision()=="b6c2d3e4f5a6"; c.rollback(); tx=c.begin()
  try:
   signal=row("junction-signal"); insert(c,signal); evidence_id="evidence-junction".ljust(36,"0"); observation_id="observation-junction".ljust(36,"0")
   c.execute(text("INSERT INTO audience_observations (id,source_namespace,source_type,observation_key,observed_at,captured_at,normalized_fact) VALUES (:id,'proof','MANUAL',repeat('o',64),now(),now(),'{}')"),{"id":observation_id})
   c.execute(text("INSERT INTO audience_evidence (id,observation_id,source_reference,captured_at,normalized_representation,evidence_fingerprint) VALUES (:id,:observation,'proof',now(),'{}',repeat('e',64))"),{"id":evidence_id,"observation":observation_id})
   c.execute(text("INSERT INTO audience_signal_evidence (signal_id,evidence_id) VALUES (:signal,:evidence)"),{"signal":signal["id"],"evidence":evidence_id})
   sp=c.begin_nested()
   with pytest.raises(IntegrityError) as error: c.execute(text("INSERT INTO audience_signal_evidence (signal_id,evidence_id) VALUES (:signal,:evidence)"),{"signal":signal["id"],"evidence":evidence_id})
   assert "uq_audience_signal_evidence_pair" in str(error.value.orig) or "audience_signal_evidence_pkey" in str(error.value.orig); sp.rollback()
   assert c.execute(text("SELECT count(*) FROM audience_signal_evidence WHERE signal_id=:signal AND evidence_id=:evidence"),{"signal":signal["id"],"evidence":evidence_id}).scalar_one()==1
  finally: tx.rollback()
