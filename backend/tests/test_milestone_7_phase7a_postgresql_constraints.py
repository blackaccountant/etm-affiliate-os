"""Guarded G5 constraints for immutable M7A qualification persistence."""
import os
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


REVISION = "d8e9f0a1b2c3"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("G5 only")


def _assessment_sql(*, intent_score="0", status="'NOT_QUALIFIED'", ruleset="repeat('a',64)", context="repeat('b',64)", memberships="repeat('c',64)"):
    measures = ", ".join(["0"] * 10 + [intent_score, "0"])
    return f"INSERT INTO audience_qualification_assessments (id,profile_id,scoring_ruleset_version,scoring_ruleset_fingerprint,scoring_ruleset_json,context_type,context_json,context_fingerprint,selected_membership_fingerprint,problem_strength,interest_alignment,research_intent,comparison_intent,evaluation_intent,pricing_intent,purchase_request_intent,purchase_signal,engagement,business_need_fit,intent_score,qualification_score,qualification_status,derived_at) VALUES (:id,:profile,'v1',{ruleset},'{{}}','NONE','{{}}',{context},{memberships},{measures},{status},now())"


def test_postgresql_m7a_constraints():
    engine = create_engine(_url.render_as_string(hide_password=False))
    subject, observation, evidence, signal, profile, segment, revision, membership, assessment = (str(uuid4()) for _ in range(9))
    try:
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == REVISION
        with engine.begin() as connection:
            token = uuid4().hex
            connection.execute(text("INSERT INTO audience_subjects (id,subject_type,created_at,updated_at) VALUES (:id,'PERSON',now(),now())"), {"id": subject})
            connection.execute(text("INSERT INTO audience_observations (id,subject_id,source_namespace,source_type,observation_key,observed_at,captured_at,normalized_fact) VALUES (:id,:subject,'m7a','MANUAL',:key,now(),now(),'{}')"), {"id": observation, "subject": subject, "key": token})
            connection.execute(text("INSERT INTO audience_evidence (id,observation_id,source_reference,captured_at,normalized_representation,evidence_fingerprint) VALUES (:id,:observation,:source,now(),'{}',repeat('e',64))"), {"id": evidence, "observation": observation, "source": token})
            connection.execute(text("INSERT INTO audience_signals (id,subject_id,signal_type,topic_slug,topic_label,intent_stage,strength,confidence,evidence_set_fingerprint,extraction_key,ruleset_version,observed_at,derived_at,created_at) VALUES (:id,:subject,'INTENT','hosting','Hosting','PRICING',50,60,repeat('d',64),:key,'v1',now(),now(),now())"), {"id": signal, "subject": subject, "key": "s" + token})
            connection.execute(text("INSERT INTO audience_profiles (id,subject_id,profile_ruleset_version,source_fingerprint,derived_at,effective_as_of,summary_json) VALUES (:id,:subject,'v1',repeat('f',64),now(),now(),'{}')"), {"id": profile, "subject": subject})
            connection.execute(text("INSERT INTO audience_segments (id,segment_key,name,created_at) VALUES (:id,:key,'M7A',now())"), {"id": segment, "key": "m7a-" + token})
            connection.execute(text("INSERT INTO audience_segment_revisions (id,segment_id,revision_number,segment_ruleset_version,definition_fingerprint,definition_json,created_at) VALUES (:id,:segment,1,'v1',repeat('g',64),'{}',now())"), {"id": revision, "segment": segment})
            connection.execute(text("INSERT INTO audience_segment_memberships (id,segment_revision_id,profile_id,is_member,evaluated_at) VALUES (:id,:revision,:profile,true,now())"), {"id": membership, "revision": revision, "profile": profile})
            connection.execute(text(_assessment_sql()), {"id": assessment, "profile": profile})
            connection.execute(text("INSERT INTO audience_qualification_assessment_memberships (assessment_id,membership_id) VALUES (:assessment,:membership)"), {"assessment": assessment, "membership": membership})
            connection.execute(text("INSERT INTO audience_qualification_contributions (id,assessment_id,source_signal_id,dimension,rule_id,strength,confidence,raw_amount,confidence_adjusted_amount,final_amount,disposition) VALUES (:id,:assessment,:signal,'pricing_intent','rule',50,60,50,30,30,'SELECTED')"), {"id": str(uuid4()), "assessment": assessment, "signal": signal})
        checks = (
            (_assessment_sql(), {"id": str(uuid4()), "profile": profile}),
            (_assessment_sql(intent_score="101", ruleset="repeat('h',64)"), {"id": str(uuid4()), "profile": profile}),
            ("INSERT INTO audience_qualification_assessment_memberships (assessment_id,membership_id) VALUES (:assessment,:membership)", {"assessment": assessment, "membership": membership}),
            ("INSERT INTO audience_qualification_contributions (id,assessment_id,source_signal_id,dimension,rule_id,strength,confidence,raw_amount,confidence_adjusted_amount,final_amount,disposition) VALUES (:id,:assessment,:signal,'pricing_intent','rule',50,60,50,30,30,'SELECTED')", {"id": str(uuid4()), "assessment": assessment, "signal": signal}),
            (_assessment_sql(status="'INVALID'", ruleset="repeat('i',64)"), {"id": str(uuid4()), "profile": profile}),
        )
        with engine.connect() as connection:
            for index, (sql, params) in enumerate(checks):
                transaction = connection.begin()
                with pytest.raises(IntegrityError) as error:
                    connection.execute(text(sql), params)
                if index in {0, 2, 3}:
                    assert getattr(error.value.orig, "pgcode", None) == "23505"
                transaction.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audience_qualification_contributions WHERE assessment_id=:id"), {"id": assessment})
            connection.execute(text("DELETE FROM audience_qualification_assessment_memberships WHERE assessment_id=:id"), {"id": assessment})
            connection.execute(text("DELETE FROM audience_qualification_assessments WHERE id=:id"), {"id": assessment})
            connection.execute(text("DELETE FROM audience_segment_memberships WHERE id=:id"), {"id": membership})
            connection.execute(text("DELETE FROM audience_segment_revisions WHERE id=:id"), {"id": revision})
            connection.execute(text("DELETE FROM audience_segments WHERE id=:id"), {"id": segment})
            connection.execute(text("DELETE FROM audience_signals WHERE id=:id"), {"id": signal})
            connection.execute(text("DELETE FROM audience_evidence WHERE id=:id"), {"id": evidence})
            connection.execute(text("DELETE FROM audience_observations WHERE id=:id"), {"id": observation})
            connection.execute(text("DELETE FROM audience_profiles WHERE id=:id"), {"id": profile})
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id": subject})
        engine.dispose()
