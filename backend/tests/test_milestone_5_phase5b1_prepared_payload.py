"""Phase 5B.1 durable, system-fingerprinted outbound payload correction."""

import hashlib
import socket

import pytest

from app.distribution.contracts import CreateDistributionRunRequest, canonicalize_prepared_content_body
from app.models.distribution_run import DistributionRun
from app.services.distribution_run_service import DistributionRunService
from tests.test_milestone_5_phase5b_distribution_domain import source


@pytest.fixture(autouse=True)
def no_configured_access(monkeypatch):
    import app.database.session as database_session

    calls = []

    def forbidden(*args, **kwargs):
        calls.append("configured infrastructure")
        raise AssertionError("Phase 5B.1 must use only isolated SQLite and no network")

    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            forbidden(*args, **kwargs)

    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    yield
    assert calls == []


def request(**changes):
    values = {
        "generated_content_artifact_id": "artifact",
        "content_evaluation_id": "evaluation",
        "platform": " WordPress ",
        "account_reference": "primary",
        "destination": "main",
    }
    values.update(changes)
    return CreateDistributionRunRequest(**values)


def test_derived_artifact_body_is_persisted_canonical_and_fingerprinted_by_system(db_session):
    artifact, _ = source(db_session)
    row = DistributionRunService(db_session).create(request())
    assert row.prepared_content_body == artifact.body == "Body"
    assert row.payload_fingerprint == hashlib.sha256(row.prepared_content_body.encode("utf-8")).hexdigest()
    assert artifact.body == "Body"


def test_newline_canonicalization_is_stored_and_used_for_the_digest(db_session):
    source(db_session)
    body = "Title\r\n\rBody\rFooter\n"
    row = DistributionRunService(db_session).create(request(prepared_content_body=body))
    assert row.prepared_content_body == "Title\n\nBody\nFooter\n"
    assert row.payload_fingerprint == hashlib.sha256(b"Title\n\nBody\nFooter\n").hexdigest()
    assert canonicalize_prepared_content_body(body) == row.prepared_content_body


def test_same_canonical_body_is_idempotent_while_changed_body_creates_distinct_intent(db_session, db_session_factory):
    source(db_session)
    service = DistributionRunService(db_session)
    first = service.create(request(prepared_content_body="body\r\n"))
    duplicate = service.create(request(prepared_content_body="body\n"))
    changed = service.create(request(prepared_content_body="changed body"))
    restarted = db_session_factory()
    try:
        after_restart = DistributionRunService(restarted).create(request(prepared_content_body="body\n"))
    finally:
        restarted.close()
    assert first.id == duplicate.id == after_restart.id
    assert changed.id != first.id and changed.idempotency_key != first.idempotency_key
    assert changed.payload_fingerprint != first.payload_fingerprint


def test_callers_cannot_supply_an_authoritative_fingerprint_or_mutate_identity_surface(db_session):
    source(db_session)
    with pytest.raises(TypeError, match="payload_fingerprint"):
        CreateDistributionRunRequest(**{**request().__dict__, "payload_fingerprint": "0" * 64})
    row = DistributionRunService(db_session).create(request(prepared_content_body="exact"))
    repository = DistributionRunService(db_session).runs
    assert not hasattr(repository, "update") and not hasattr(repository, "publish")
    assert row.prepared_content_body == "exact"
    columns = set(DistributionRun.__table__.columns)
    assert {"password", "token", "access_token", "refresh_token", "api_key", "secret", "cookie"}.isdisjoint(columns)


@pytest.mark.parametrize("body,error", [(object(), "must be text"), ("\r\n\t", "is required")])
def test_prepared_body_requires_meaningful_text_without_whitespace_rewriting(db_session, body, error):
    source(db_session)
    with pytest.raises(ValueError, match=error):
        DistributionRunService(db_session).create(request(prepared_content_body=body))
