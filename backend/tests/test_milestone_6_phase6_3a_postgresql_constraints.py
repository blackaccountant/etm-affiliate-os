"""Guarded G5 constraints for M6.3A immutable persistence."""
import os
from uuid import uuid4
import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

REVISION = "c7d3e4f5a6b7"; _raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw: pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"): raise RuntimeError("G5 only")

def test_postgresql_m63a_unique_and_check_constraints():
    engine=create_engine(_url.render_as_string(hide_password=False)); token=uuid4().hex; subject, observation, evidence, signal, profile, segment, revision = (str(uuid4()) for _ in range(7))
    try:
        with engine.connect() as c:
            assert MigrationContext.configure(c).get_current_revision() == REVISION
        with engine.begin() as c:
            c.execute(text("INSERT INTO audience_subjects (id,subject_type,created_at,updated_at) VALUES (:id,'PERSON',now(),now())"), {"id":subject})
            c.execute(text("INSERT INTO audience_observations (id,subject_id,source_namespace,source_type,observation_key,observed_at,captured_at,normalized_fact) VALUES (:id,:subject,'m63a-constraints','MANUAL',:key,now(),now(),'{}')"), {"id":observation,"subject":subject,"key":"o"+token})
            c.execute(text("INSERT INTO audience_evidence (id,observation_id,source_reference,captured_at,normalized_representation,evidence_fingerprint) VALUES (:id,:observation,:token,now(),'{}',:fingerprint)"), {"id":evidence,"observation":observation,"token":token,"fingerprint":"e"*64})
            c.execute(text("INSERT INTO audience_signals (id,subject_id,signal_type,topic_slug,topic_label,intent_stage,strength,confidence,evidence_set_fingerprint,extraction_key,ruleset_version,observed_at,derived_at,created_at) VALUES (:id,:subject,'INTENT','hosting','Hosting','PRICING',50,60,repeat('d',64),:key,'v1',now(),now(),now())"), {"id":signal,"subject":subject,"key":"s"+token})
            c.execute(text("INSERT INTO audience_profiles (id,subject_id,profile_ruleset_version,source_fingerprint,derived_at,effective_as_of,summary_json) VALUES (:id,:subject,'v1',repeat('a',64),now(),now(),'{}')"), {"id":profile,"subject":subject})
            c.execute(text("INSERT INTO audience_profile_signals (profile_id,signal_id) VALUES (:profile,:signal)"), {"profile":profile,"signal":signal})
            c.execute(text("INSERT INTO audience_segments (id,segment_key,name,created_at) VALUES (:id,:key,'Test',now())"), {"id":segment,"key":"m63a-"+token})
            c.execute(text("INSERT INTO audience_segment_revisions (id,segment_id,revision_number,segment_ruleset_version,definition_fingerprint,definition_json,created_at) VALUES (:id,:segment,1,'v1',repeat('b',64),'{}',now())"), {"id":revision,"segment":segment})
            c.execute(text("INSERT INTO audience_segment_memberships (id,segment_revision_id,profile_id,is_member,evaluated_at) VALUES (:id,:revision,:profile,false,now())"), {"id":str(uuid4()),"revision":revision,"profile":profile})
        with engine.connect() as c:
            for sql, params in (("INSERT INTO audience_profiles (id,subject_id,profile_ruleset_version,source_fingerprint,derived_at,effective_as_of,summary_json) VALUES (:id,:subject,'v1',repeat('a',64),now(),now(),'{}')", {"id":str(uuid4()),"subject":subject}), ("INSERT INTO audience_profile_signals (profile_id,signal_id) VALUES (:profile,:signal)", {"profile":profile,"signal":signal}), ("INSERT INTO audience_segments (id,segment_key,name,created_at) VALUES (:id,:key,'Again',now())", {"id":str(uuid4()),"key":"m63a-"+token}), ("INSERT INTO audience_segment_revisions (id,segment_id,revision_number,segment_ruleset_version,definition_fingerprint,definition_json,created_at) VALUES (:id,:segment,0,'v1',repeat('c',64),'{}',now())", {"id":str(uuid4()),"segment":segment}), ("INSERT INTO audience_segment_memberships (id,segment_revision_id,profile_id,is_member,evaluated_at) VALUES (:id,:revision,:profile,true,now())", {"id":str(uuid4()),"revision":revision,"profile":profile})):
                tx=c.begin()
                with pytest.raises(IntegrityError) as error: c.execute(text(sql), params)
                if "audience_profile_signals" in sql: assert getattr(error.value.orig, "pgcode", None) == "23505"
                tx.rollback()
    finally:
        with engine.begin() as c:
            tables = __import__("sqlalchemy").inspect(c).get_table_names()
            if "audience_segment_memberships" in tables:
                c.execute(text("DELETE FROM audience_segment_memberships WHERE profile_id=:profile"), {"profile":profile})
                c.execute(text("DELETE FROM audience_segment_revisions WHERE id=:id"), {"id":revision})
                c.execute(text("DELETE FROM audience_segments WHERE id=:id"), {"id":segment})
                c.execute(text("DELETE FROM audience_profile_signals WHERE profile_id=:profile"), {"profile":profile})
                c.execute(text("DELETE FROM audience_profiles WHERE id=:id"), {"id":profile})
                c.execute(text("DELETE FROM audience_signals WHERE id=:id"), {"id":signal})
                c.execute(text("DELETE FROM audience_evidence WHERE id=:id"), {"id":evidence})
                c.execute(text("DELETE FROM audience_observations WHERE id=:id"), {"id":observation})
            c.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id":subject})
        engine.dispose()
