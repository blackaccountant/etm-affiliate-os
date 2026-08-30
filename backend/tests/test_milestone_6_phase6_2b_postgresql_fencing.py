"""Guarded G5 proof that the audience write fence holds a PostgreSQL row lock."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.audience import AudienceSignal, AudienceSignalEvidence
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_service import AudienceSignalService, SignalCandidate
from app.services.execution_lease import ExecutionLeaseAuthority
from app.workforce.status import WorkerStatus


_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1"
        and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("G5 only")


@pytest.fixture(scope="module")
def engine():
    value = _url.render_as_string(hide_password=False)
    engine = create_engine(value, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "b6c2d3e4f5a6"
        yield engine
    finally:
        engine.dispose()


def seed(factory):
    db = factory()
    token = uuid4().hex
    worker_name = f"Fence proof {token}"
    try:
        foundation = AudienceFoundationService(db)
        observation = foundation.ingest_observation(
            research_run_id=None, subject_id=None, source_namespace="fence-proof",
            source_type="MANUAL", external_observation_id=None,
            source_reference=f"observation:{token}", observed_at=datetime.now(timezone.utc),
            normalized_fact={"event": "pricing"},
        )
        evidence = foundation.record_evidence(
            observation_id=observation.id, source_reference=f"evidence:{token}",
            normalized_representation={"event": "pricing"},
        )
        mission = MissionRepository(db).create(str(uuid4()), "Fence proof", "prove lock", "fence_proof")
        workers = WorkerRepository(db)
        workers.create(worker_name, "Test", ["fence"], WorkerStatus.ONLINE)
        assert workers.claim(worker_name, mission.id)
        execution = ExecutionRepository(db).create("fence_proof", "RUNNING", mission.id, mission.name, worker_name)
        authority = ExecutionLeaseAuthority.fresh(execution.id, 1)
        assert ExecutionRepository(db).acquire_lease(authority, 60)
        return token, worker_name, mission.id, observation.id, evidence.id, authority
    finally:
        db.close()


def cleanup(engine, token, worker_name, mission_id, observation_id):
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM audience_signal_evidence WHERE signal_id IN (SELECT id FROM audience_signals WHERE metadata_json->>'proof' = :token)"), {"token": token})
        connection.execute(text("DELETE FROM audience_signals WHERE metadata_json->>'proof' = :token"), {"token": token})
        connection.execute(text("DELETE FROM audience_evidence WHERE observation_id = :id"), {"id": observation_id})
        connection.execute(text("DELETE FROM audience_observations WHERE id = :id"), {"id": observation_id})
        connection.execute(text("DELETE FROM executions WHERE mission_id = :id"), {"id": mission_id})
        connection.execute(text("DELETE FROM missions WHERE id = :id"), {"id": mission_id})
        connection.execute(text("DELETE FROM workers WHERE name = :name"), {"name": worker_name})


def test_postgresql_fence_holds_row_lock_through_signal_write(engine):
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    token, worker_name, mission_id, observation_id, evidence_id, authority = seed(factory)
    writer = competitor = verifier = None
    try:
        writer, competitor = factory(), factory()
        writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar_one()
        competitor_pid = competitor.execute(text("SELECT pg_backend_pid()")).scalar_one()
        assert writer is not competitor and writer_pid != competitor_pid
        assert ExecutionRepository(writer).verify_active_authority(authority).id == authority.execution_id

        competitor.execute(text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(OperationalError) as blocked:
            competitor.execute(text("UPDATE executions SET lease_owner = 'replacement', lease_generation = lease_generation + 1 WHERE id = :id"), {"id": authority.execution_id})
        assert getattr(blocked.value.orig, "pgcode", None) == "55P03" or getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        competitor.rollback()

        signal = AudienceSignalService(writer).persist(
            SignalCandidate("INTENT", "pricing", "Pricing", "PRICING", 50, 60, [evidence_id], "audience-signal-extraction-v1", metadata_json={"proof": token}),
            subject_id=None,
        )
        assert signal.id
        writer.commit()

        transition = factory()
        try:
            transition.execute(text("UPDATE executions SET lease_owner = 'replacement', lease_generation = lease_generation + 1 WHERE id = :id"), {"id": authority.execution_id})
            transition.commit()
        finally:
            transition.close()

        verifier = factory()
        with pytest.raises(ExecutionLeaseLostError):
            ExecutionRepository(verifier).verify_active_authority(authority)
        assert verifier.query(AudienceSignal).filter_by(id=signal.id).count() == 1
        assert verifier.query(AudienceSignalEvidence).filter_by(signal_id=signal.id).count() == 1
        assert verifier.query(AudienceSignal).filter_by(id=signal.id).count() == 1
    finally:
        for session in (verifier, competitor, writer):
            if session is not None:
                session.close()
        cleanup(engine, token, worker_name, mission_id, observation_id)
