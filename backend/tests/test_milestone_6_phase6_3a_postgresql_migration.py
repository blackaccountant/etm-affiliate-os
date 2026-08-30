"""Guarded G5 roundtrip proof for additive M6.3A tables."""
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.audience import AudienceEvidence, AudienceObservation, AudienceSignal, AudienceSubject
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate
from app.core.config import settings

REVISION, PREVIOUS = "c7d3e4f5a6b7", "b6c2d3e4f5a6"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw: pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"): raise RuntimeError("G5 only")

def _revision(engine):
    with engine.connect() as connection: return MigrationContext.configure(connection).get_current_revision()


def _cleanup_target_fixture(engine, *, signal_id, evidence_id, observation_id, subject_id):
    """Remove only the exact target fixture rows in dependency order."""
    with engine.begin() as connection:
        if signal_id is not None:
            connection.execute(text("DELETE FROM audience_signal_evidence WHERE signal_id=:id"), {"id": signal_id})
            connection.execute(text("DELETE FROM audience_signals WHERE id=:id"), {"id": signal_id})
        if evidence_id is not None:
            connection.execute(text("DELETE FROM audience_evidence WHERE id=:id"), {"id": evidence_id})
        if observation_id is not None:
            connection.execute(text("DELETE FROM audience_observations WHERE id=:id"), {"id": observation_id})
        if subject_id is not None:
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id": subject_id})


def test_m63a_upgrade_downgrade_upgrade_preserves_frozen_audience_data():
    engine = create_engine(_url.render_as_string(hide_password=False)); config = Config("alembic.ini"); config.set_main_option("sqlalchemy.url", _url.render_as_string(hide_password=False)); previous_url = settings.DATABASE_URL; settings.DATABASE_URL = _url.render_as_string(hide_password=False)
    token = uuid4().hex; signal_id = evidence_id = observation_id = subject_id = None
    sentinel_subject_id = str(uuid4())
    try:
        # A prior successful run intentionally leaves guarded G5 at REVISION.
        # Normalize that accepted final state before proving the b6 roundtrip.
        if _revision(engine) == REVISION:
            command.downgrade(config, PREVIOUS)
            engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False))
        assert _revision(engine) == PREVIOUS
        try:
            db = sessionmaker(bind=engine)()
            try:
                foundation = AudienceFoundationService(db); subject = foundation.create_subject("PERSON")
                sentinel = AudienceSubject(id=sentinel_subject_id, subject_type="ANONYMOUS")
                db.add(sentinel)
                observation = foundation.ingest_observation(research_run_id=None, subject_id=subject.id, source_namespace="m63a-migration", source_type="MANUAL", external_observation_id=None, source_reference=token, observed_at=datetime.now(timezone.utc), normalized_fact={"event": "pricing"})
                evidence = foundation.record_evidence(observation_id=observation.id, source_reference=token, normalized_representation={"event": "pricing"})
                signal = AudienceSignalService(db).persist(SignalCandidate("INTENT", "hosting", "Hosting", "PRICING", 50, 60, [evidence.id], "v1"), subject_id=subject.id)
                db.commit()
                signal_id, evidence_id, observation_id, subject_id = signal.id, evidence.id, observation.id, subject.id
                snapshot = (subject.id, observation.id, evidence.id, signal.id)
            finally:
                db.close()
            command.upgrade(config, REVISION); engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False)); assert _revision(engine) == REVISION
            assert {"audience_profiles", "audience_profile_signals", "audience_segments", "audience_segment_revisions", "audience_segment_memberships"} <= set(inspect(engine).get_table_names())
            command.downgrade(config, PREVIOUS); engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False)); assert _revision(engine) == PREVIOUS
            assert not {"audience_profiles", "audience_profile_signals", "audience_segments", "audience_segment_revisions", "audience_segment_memberships"} & set(inspect(engine).get_table_names())
            db = sessionmaker(bind=engine)()
            try:
                assert all(db.get(model, value) is not None for model, value in zip((AudienceSubject, AudienceObservation, AudienceEvidence, AudienceSignal), snapshot))
            finally:
                db.close()
            command.upgrade(config, REVISION); engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False)); assert _revision(engine) == REVISION
        finally:
            _cleanup_target_fixture(engine, signal_id=signal_id, evidence_id=evidence_id, observation_id=observation_id, subject_id=subject_id)
        verification = sessionmaker(bind=engine)()
        try:
            assert verification.query(AudienceSubject).filter_by(id=subject_id).count() == 0
            assert verification.query(AudienceSubject).filter_by(id=sentinel_subject_id).count() == 1
        finally:
            verification.close()
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id": sentinel_subject_id})
        final_verification = sessionmaker(bind=engine)()
        try:
            assert final_verification.query(AudienceSubject).filter_by(id=subject_id).count() == 0
            assert final_verification.query(AudienceSubject).filter_by(id=sentinel_subject_id).count() == 0
        finally:
            final_verification.close()
    finally:
        _cleanup_target_fixture(engine, signal_id=signal_id, evidence_id=evidence_id, observation_id=observation_id, subject_id=subject_id)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id": sentinel_subject_id})
        settings.DATABASE_URL = previous_url; engine.dispose()
