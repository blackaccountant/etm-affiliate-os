"""Opt-in PostgreSQL proofs for mission idempotency and worker atomicity."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository
from app.workforce.status import WorkerStatus


if os.getenv("ETM_RUN_POSTGRES_INTEGRATION") != "1":
    pytest.skip(
        "Requires a local disposable PostgreSQL database; set "
        "ETM_RUN_POSTGRES_INTEGRATION=1 to run.",
        allow_module_level=True,
    )


POSTGRES_URL = os.getenv("ETM_POSTGRES_INTEGRATION_URL")
if not POSTGRES_URL:
    raise RuntimeError(
        "ETM_POSTGRES_INTEGRATION_URL must name a local disposable database."
    )

url = make_url(POSTGRES_URL)
if url.host not in {"localhost", "127.0.0.1", "::1"}:
    raise RuntimeError("PostgreSQL integration tests require a local database.")
if not url.database or not url.database.startswith("etm_phase2_"):
    raise RuntimeError(
        "PostgreSQL integration database name must start with 'etm_phase2_'."
    )


@pytest.fixture(scope="module")
def postgres_session_factory():
    engine = create_engine(POSTGRES_URL)
    Base.metadata.create_all(bind=engine, tables=[MissionRecord.__table__, Worker.__table__])
    try:
        yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    finally:
        engine.dispose()


def test_postgres_worker_claim_race(postgres_session_factory):
    worker_name = f"claim-{uuid4()}"
    setup = postgres_session_factory()
    WorkerRepository(setup).create(
        name=worker_name,
        worker_type="Test",
        status=WorkerStatus.ONLINE,
    )
    setup.close()

    def claim(mission_id):
        session = postgres_session_factory()
        try:
            return WorkerRepository(session).claim(worker_name, mission_id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["mission-a", "mission-b"]))

    inspect = postgres_session_factory()
    try:
        worker = WorkerRepository(inspect).get_by_name(worker_name)
        assert results.count(True) == 1
        assert results.count(False) == 1
        assert worker.status == WorkerStatus.BUSY.value
        assert worker.current_mission_id in {"mission-a", "mission-b"}
    finally:
        inspect.close()


def test_postgres_mission_idempotency_race(postgres_session_factory):
    key = f"idempotency-{uuid4()}"

    def create(mission_id):
        session = postgres_session_factory()
        try:
            return MissionRepository(session).create(
                mission_id=mission_id,
                name="Test",
                objective="Verify idempotency",
                workflow_name="test",
                idempotency_key=key,
            ).id
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        mission_ids = list(executor.map(create, [str(uuid4()), str(uuid4())]))

    inspect = postgres_session_factory()
    try:
        records = (
            inspect.query(MissionRecord)
            .filter(MissionRecord.idempotency_key == key)
            .all()
        )
        assert len(records) == 1
        assert mission_ids == [records[0].id, records[0].id]
    finally:
        inspect.close()


def test_postgres_release_is_idempotent(postgres_session_factory):
    worker_name = f"release-{uuid4()}"
    mission_id = str(uuid4())
    setup = postgres_session_factory()
    repository = WorkerRepository(setup)
    repository.create(
        name=worker_name,
        worker_type="Test",
        status=WorkerStatus.ONLINE,
    )
    assert repository.claim(worker_name, mission_id) is True
    setup.close()

    first = postgres_session_factory()
    second = postgres_session_factory()
    try:
        assert WorkerRepository(first).release(worker_name, mission_id, success=False) is True
        assert WorkerRepository(second).release(worker_name, mission_id, success=False) is False
    finally:
        first.close()
        second.close()

    inspect = postgres_session_factory()
    try:
        worker = WorkerRepository(inspect).get_by_name(worker_name)
        assert worker.missions_completed == 1
        assert worker.missions_failed == 1
        assert worker.success_rate == 0.0
    finally:
        inspect.close()
