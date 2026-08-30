"""Guarded G5 proof that identical audience launches converge to one operation."""

import json
import os
import threading
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.audience.normalization import signal_extraction_input_fingerprint
from app.audience.signal_extraction_mission_contracts import (
    AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1,
    AudienceSignalExtractionSnapshot,
    audience_signal_extraction_mission_idempotency_key,
)
from app.models.audience import AudienceResearchRun, AudienceSignal, AudienceSignalEvidence
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.audience_repository import AudienceRepository
from app.repositories.worker_repository import WorkerRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.audience_signal_extraction_mission_launch_service import (
    AudienceSignalExtractionMissionLaunchService,
)
from app.workforce.status import WorkerStatus


_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (
    _url.drivername.startswith("postgresql")
    and _url.host == "127.0.0.1"
    and _url.port == 5432
    and _url.database == "etm_affiliate_os_g5_test"
):
    raise RuntimeError("G5 only")


@pytest.fixture(scope="module")
def engine():
    value = _url.render_as_string(hide_password=False)
    result = create_engine(value, pool_pre_ping=True)
    try:
        with result.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "b6c2d3e4f5a6"
        yield result
    finally:
        result.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed(factory):
    db = factory()
    token = uuid4().hex
    worker_name = f"Audience launch race {token}"
    try:
        foundation = AudienceFoundationService(db)
        observation = foundation.ingest_observation(
            research_run_id=None,
            subject_id=None,
            source_namespace="audience-launch-race",
            source_type="MANUAL",
            external_observation_id=None,
            source_reference=f"observation:{token}",
            observed_at=datetime.now(timezone.utc),
            normalized_fact={"event": "pricing"},
        )
        evidence = foundation.record_evidence(
            observation_id=observation.id,
            source_reference=f"evidence:{token}",
            normalized_representation={"event": "pricing"},
        )
        WorkerRepository(db).create(
            worker_name,
            "Test",
            ["audience_signal_extraction"],
            WorkerStatus.ONLINE,
        )
        snapshot = AudienceSignalExtractionSnapshot(
            observation.id,
            AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1,
            signal_extraction_input_fingerprint(
                observation_id=observation.id,
                observation_key=observation.observation_key,
                evidence=[(evidence.id, evidence.evidence_fingerprint)],
            ),
            (evidence.id,),
        )
        return token, worker_name, observation.id, snapshot
    finally:
        db.close()


def _cleanup(engine, *, worker_name, observation_id, research_run_key, mission_key):
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM executions WHERE mission_id IN (SELECT id FROM missions WHERE idempotency_key = :mission_key)"),
            {"mission_key": mission_key},
        )
        connection.execute(text("DELETE FROM missions WHERE idempotency_key = :mission_key"), {"mission_key": mission_key})
        connection.execute(text("DELETE FROM workers WHERE name = :worker_name"), {"worker_name": worker_name})
        connection.execute(
            text("DELETE FROM audience_signal_evidence WHERE evidence_id IN (SELECT id FROM audience_evidence WHERE observation_id = :observation_id)"),
            {"observation_id": observation_id},
        )
        connection.execute(text("DELETE FROM audience_evidence WHERE observation_id = :observation_id"), {"observation_id": observation_id})
        connection.execute(text("DELETE FROM audience_observations WHERE id = :observation_id"), {"observation_id": observation_id})
        connection.execute(text("DELETE FROM audience_research_runs WHERE idempotency_key = :research_run_key"), {"research_run_key": research_run_key})


def test_postgresql_concurrent_identical_launch_converges_to_one_operation(factory, engine, monkeypatch):
    token, worker_name, observation_id, snapshot = _seed(factory)
    expected_run_key = AudienceSignalExtractionMissionLaunchService._research_run_key(snapshot)
    expected_mission_key = audience_signal_extraction_mission_idempotency_key(
        snapshot.observation_id, snapshot.ruleset_version, snapshot.input_fingerprint,
    )
    ready = threading.Barrier(3)
    race_gate = threading.Barrier(2)
    results, errors, pids = [], [], []
    result_lock = threading.Lock()
    original = AudienceFoundationService.get_or_create_research_run

    def synchronized_get_or_create(self, *args, **kwargs):
        race_gate.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AudienceFoundationService, "get_or_create_research_run", synchronized_get_or_create)

    def launch_contender():
        db = factory()
        try:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with result_lock:
                pids.append(pid)
            ready.wait(timeout=10)
            result = AudienceSignalExtractionMissionLaunchService(session_factory=lambda: db).launch(
                observation_id,
                ruleset_version=snapshot.ruleset_version,
            )
            with result_lock:
                results.append(result)
        except Exception as error:  # The assertion below reports every escaped persistence race error.
            with result_lock:
                errors.append(error)
        finally:
            db.close()

    try:
        threads = [threading.Thread(target=launch_contender) for _ in range(2)]
        for thread in threads:
            thread.start()
        ready.wait(timeout=10)
        for thread in threads:
            thread.join(20)

        assert all(not thread.is_alive() for thread in threads)
        assert len(pids) == 2 and pids[0] != pids[1]
        assert errors == []
        assert len(results) == 2
        assert {result.audience_research_run_id for result in results}
        assert len({result.audience_research_run_id for result in results}) == 1
        assert len({result.mission_id for result in results}) == 1
        assert {result.idempotency_key for result in results} == {expected_mission_key}
        assert all(isinstance(result.created, bool) for result in results)

        research_run_id = results[0].audience_research_run_id
        mission_id = results[0].mission_id
        verifier = factory()
        try:
            run = verifier.query(AudienceResearchRun).filter_by(idempotency_key=expected_run_key).one()
            mission = verifier.query(MissionRecord).filter_by(idempotency_key=expected_mission_key).one()
            executions = verifier.query(Execution).filter_by(mission_id=mission.id).all()
            worker = verifier.get(Worker, worker_name)
            evidence_ids = tuple(item.id for item in AudienceRepository(verifier).evidence_for_observation(observation_id))
            assert run.id == research_run_id
            assert mission.id == mission_id
            assert verifier.query(AudienceResearchRun).filter_by(idempotency_key=expected_run_key).count() == 1
            assert verifier.query(MissionRecord).filter_by(idempotency_key=expected_mission_key).count() == 1
            assert run.metadata_json == snapshot.to_metadata()
            assert tuple(sorted(run.metadata_json["evidence_ids"])) == tuple(sorted(evidence_ids)) == snapshot.evidence_ids
            assert run.metadata_json["input_fingerprint"] == snapshot.input_fingerprint
            assert json.loads(mission.input_data) == {"audience_research_run_id": run.id}
            assert len(executions) == 1
            execution = executions[0]
            assert execution.status == "RUNNING"
            assert execution.lease_generation == 1
            assert execution.lease_owner and execution.lease_expires_at is not None
            assert worker.status == WorkerStatus.BUSY.value and worker.current_mission_id == mission.id
            assert verifier.query(AudienceSignal).count() == 0
            assert verifier.query(AudienceSignalEvidence).count() == 0
        finally:
            verifier.close()
    finally:
        _cleanup(
            engine,
            worker_name=worker_name,
            observation_id=observation_id,
            research_run_key=expected_run_key,
            mission_key=expected_mission_key,
        )
