import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.mission.status import MissionStatus
from app.models.mission_record import MissionRecord
from app.repositories.mission_repository import MissionRepository


def create_mission(repository, mission_id="mission-1", **overrides):
    values = {
        "mission_id": mission_id,
        "name": "Affiliate Discovery",
        "objective": "Find affiliate opportunities",
        "workflow_name": "affiliate_discovery",
    }
    values.update(overrides)
    return repository.create(**values)


def test_create_and_read_mission_with_utc_timestamps(db_session):
    record = create_mission(MissionRepository(db_session))

    fetched = MissionRepository(db_session).get_by_id(record.id)

    assert fetched.id == "mission-1"
    assert fetched.status == MissionStatus.CREATED.value
    assert fetched.created_at.tzinfo is not None
    assert fetched.updated_at.tzinfo is not None


def test_mission_persists_input_data_and_status_update(db_session):
    repository = MissionRepository(db_session)
    record = create_mission(repository, input_data={"source": "test"})

    updated = repository.update_status(
        record.id,
        MissionStatus.COMPLETED,
        result_data={"success": True},
        last_error=None,
    )

    assert json.loads(updated.input_data) == {"source": "test"}
    assert json.loads(updated.result_data) == {"success": True}
    assert updated.last_error is None
    assert updated.status == MissionStatus.COMPLETED.value
    assert updated.completed_at is not None
    assert updated.completed_at.tzinfo is not None
    assert repository.list_by_status(MissionStatus.COMPLETED) == [updated]


def test_mission_persists_result_and_error_data(db_session):
    repository = MissionRepository(db_session)
    record = create_mission(repository)

    updated = repository.update_status(
        record.id,
        MissionStatus.FAILED,
        result_data={"partial": True},
        last_error="provider timeout",
    )

    assert json.loads(updated.result_data) == {"partial": True}
    assert updated.last_error == "provider timeout"


def test_idempotency_key_lookup_and_duplicate_create_return_same_row(db_session):
    repository = MissionRepository(db_session)
    first = create_mission(repository, idempotency_key="request-1")
    duplicate = create_mission(
        repository,
        mission_id="mission-2",
        idempotency_key="request-1",
    )

    assert repository.get_by_idempotency_key("request-1") is first
    assert duplicate.id == first.id
    assert db_session.query(MissionRecord).count() == 1


def test_duplicate_mission_id_without_idempotency_is_rejected(db_session):
    repository = MissionRepository(db_session)
    create_mission(repository)

    with pytest.raises(IntegrityError):
        create_mission(repository)
