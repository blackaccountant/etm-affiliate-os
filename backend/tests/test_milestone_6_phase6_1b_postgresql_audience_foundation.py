"""Guarded PostgreSQL concurrency proofs for the M6.1 audience foundation."""

from datetime import datetime, timezone
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.audience import (
    AudienceEvidence,
    AudienceExternalIdentity,
    AudienceObservation,
    AudienceResearchRun,
    AudienceSubject,
)
from app.services.audience_foundation_service import AudienceFoundationService


REVISION = "a6b1c2d3e4f5"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("M6.1B requires guarded local G5 only.")


@pytest.fixture(scope="module")
def engine():
    value = _url.render_as_string(hide_password=False)
    engine = create_engine(value, pool_pre_ping=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    with engine.begin() as connection:
        names = [name for name in inspect(engine).get_table_names() if name != "alembic_version"]
        connection.execute(text("TRUNCATE TABLE " + ", ".join(f'\"{name}\"' for name in names) + " RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _race(factory, *actions):
    barrier = threading.Barrier(len(actions))
    outcomes = []
    lock = threading.Lock()

    def invoke(action):
        db = factory()
        try:
            barrier.wait()
            value = action(db)
            db.commit()
            outcome = ("ok", getattr(value, "id", value))
        except ValueError as exc:
            db.rollback()
            outcome = ("rejected", str(exc))
        except Exception as exc:
            db.rollback()
            outcome = ("error", repr(exc))
        finally:
            db.close()
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=invoke, args=(action,)) for action in actions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert all(not thread.is_alive() for thread in threads)
    assert not [item for item in outcomes if item[0] == "error"]
    return outcomes


def _subject(factory, reference="subject-1"):
    db = factory()
    try:
        subject = AudienceFoundationService(db).get_or_create_subject_for_identity(
            subject_type="PERSON", source_namespace="public-social", identity_type="account", reference=reference,
        )
        db.commit()
        return subject.id
    finally:
        db.close()


def _observation(service, *, external_id="observation-1", fact=None, subject_id=None):
    return service.ingest_observation(
        research_run_id=None,
        subject_id=subject_id,
        source_namespace="public-web",
        source_type="PUBLIC_WEB",
        external_observation_id=external_id,
        source_reference=f"https://example.test/{external_id}",
        observed_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        normalized_fact=fact or {"event": "pricing_page_view", "count": 3},
        metadata_json={"fixture": "m6.1b"},
    )


def test_concurrent_identical_identity_resolves_one_subject_and_identity(factory):
    outcomes = _race(
        factory,
        lambda db: AudienceFoundationService(db).get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="first-party", identity_type="email", reference=" Member@Example.test "),
        lambda db: AudienceFoundationService(db).get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="first-party", identity_type="email", reference="member@example.test"),
    )
    db = factory()
    try:
        identities = db.query(AudienceExternalIdentity).filter_by(source_namespace="first-party", identity_type="email", normalized_reference="member@example.test").all()
        assert len(identities) == 1
        assert {item[1] for item in outcomes} == {identities[0].subject_id}
        assert db.query(AudienceSubject).count() == 1
    finally:
        db.close()


def test_cross_subject_identity_conflict_has_one_owner(factory):
    first, second = _subject(factory, "first"), _subject(factory, "second")
    outcomes = _race(
        factory,
        lambda db: AudienceFoundationService(db).attach_external_identity(first, source_namespace="directory", identity_type="domain", reference="Example.test"),
        lambda db: AudienceFoundationService(db).attach_external_identity(second, source_namespace="directory", identity_type="domain", reference="example.test"),
    )
    db = factory()
    try:
        identities = db.query(AudienceExternalIdentity).filter_by(source_namespace="directory", identity_type="domain", normalized_reference="example.test").all()
        assert len(identities) == 1 and identities[0].subject_id in {first, second}
        assert sorted(item[0] for item in outcomes) == ["ok", "rejected"]
    finally:
        db.close()


def test_research_run_identical_and_conflicting_idempotency_races(factory):
    same = _race(
        factory,
        lambda db: AudienceFoundationService(db).get_or_create_research_run(scope_type="category", scope_reference="hosting", idempotency_key="research:hosting", metadata_json={"language": "en"}),
        lambda db: AudienceFoundationService(db).get_or_create_research_run(scope_type="category", scope_reference="hosting", idempotency_key="research:hosting", metadata_json={"language": "en"}),
    )
    assert len({item[1] for item in same}) == 1
    conflict = _race(
        factory,
        lambda db: AudienceFoundationService(db).get_or_create_research_run(scope_type="category", scope_reference="email", idempotency_key="research:conflict"),
        lambda db: AudienceFoundationService(db).get_or_create_research_run(scope_type="category", scope_reference="hosting", idempotency_key="research:conflict"),
    )
    db = factory()
    try:
        assert db.query(AudienceResearchRun).filter_by(idempotency_key="research:hosting").count() == 1
        assert db.query(AudienceResearchRun).filter_by(idempotency_key="research:conflict").count() == 1
        assert sorted(item[0] for item in conflict) == ["ok", "rejected"]
    finally:
        db.close()


def test_observation_duplicate_conflict_subjectless_and_same_subject_lineage(factory):
    duplicate = _race(factory, lambda db: _observation(AudienceFoundationService(db)), lambda db: _observation(AudienceFoundationService(db)))
    assert len({item[1] for item in duplicate}) == 1
    conflict = _race(
        factory,
        lambda db: _observation(AudienceFoundationService(db), external_id="observation-conflict", fact={"event": "pricing"}),
        lambda db: _observation(AudienceFoundationService(db), external_id="observation-conflict", fact={"event": "checkout"}),
    )
    subjectless = _race(
        factory,
        lambda db: _observation(AudienceFoundationService(db), external_id="subjectless"),
        lambda db: _observation(AudienceFoundationService(db), external_id="subjectless"),
    )
    subject_id = _subject(factory, "lineage")
    distinct = _race(
        factory,
        lambda db: _observation(AudienceFoundationService(db), external_id="lineage-a", subject_id=subject_id),
        lambda db: _observation(AudienceFoundationService(db), external_id="lineage-b", subject_id=subject_id),
    )
    db = factory()
    try:
        assert sorted(item[0] for item in conflict) == ["ok", "rejected"]
        assert len({item[1] for item in subjectless}) == 1
        assert db.query(AudienceObservation).filter_by(subject_id=subject_id).count() == 2
        assert len({item[1] for item in distinct}) == 2
    finally:
        db.close()


def test_evidence_duplicate_conflict_and_cross_observation_lineage(factory):
    setup = factory()
    try:
        first = _observation(AudienceFoundationService(setup), external_id="evidence-a")
        second = _observation(AudienceFoundationService(setup), external_id="evidence-b")
        setup.commit()
        first_id, second_id = first.id, second.id
    finally:
        setup.close()
    duplicate = _race(
        factory,
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=first_id, source_reference="capture", normalized_representation={"text": "pricing"}, content_fingerprint="a" * 64),
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=first_id, source_reference="capture", normalized_representation={"text": "pricing"}, content_fingerprint="a" * 64),
    )
    conflict = _race(
        factory,
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=first_id, source_reference="conflict", source_uri="https://one.test", normalized_representation={"text": "same"}, content_fingerprint="b" * 64),
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=first_id, source_reference="conflict", source_uri="https://two.test", normalized_representation={"text": "same"}, content_fingerprint="b" * 64),
    )
    cross = _race(
        factory,
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=first_id, source_reference="capture", normalized_representation={"text": "shared"}, content_fingerprint="c" * 64),
        lambda db: AudienceFoundationService(db).record_evidence(observation_id=second_id, source_reference="capture", normalized_representation={"text": "shared"}, content_fingerprint="c" * 64),
    )
    db = factory()
    try:
        assert len({item[1] for item in duplicate}) == 1
        assert sorted(item[0] for item in conflict) == ["ok", "rejected"]
        assert len({item[1] for item in cross}) == 2
        assert db.query(AudienceEvidence).filter_by(observation_id=first_id).count() == 3
        assert db.query(AudienceEvidence).filter_by(observation_id=second_id).count() == 1
    finally:
        db.close()


def test_normalization_display_name_non_dedupe_weak_links_and_atomic_rollback(factory):
    db = factory()
    try:
        service = AudienceFoundationService(db)
        email = service.get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="first-party", identity_type="email", reference=" A@Example.test ")
        domain = service.get_or_create_subject_for_identity(subject_type="ORGANIZATION", source_namespace="directory", identity_type="domain", reference="https://WWW.Example.test/")
        account_a = service.get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="social", identity_type="account", reference="CaseSensitive", metadata_json={"display_name": "Alex"})
        account_b = service.get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="social", identity_type="account", reference="casesensitive", metadata_json={"display_name": "Alex"})
        db.commit()
        assert email.id != domain.id and account_a.id != account_b.id
        assert service.records.external_identity("first-party", "email", "a@example.test").subject_id == email.id
        assert service.records.external_identity("directory", "domain", "example.test").subject_id == domain.id
        assert service.records.external_identity("social", "account", "CaseSensitive").subject_id == account_a.id
        assert service.records.external_identity("social", "account", "casesensitive").subject_id == account_b.id
    finally:
        db.close()

    winner = _subject(factory, "rollback-winner")
    outcomes = _race(
        factory,
        lambda session: AudienceFoundationService(session).get_or_create_subject_for_identity(subject_type="PERSON", source_namespace="social", identity_type="account", reference="rollback-race"),
        lambda session: AudienceFoundationService(session).attach_external_identity(winner, source_namespace="social", identity_type="account", reference="rollback-race"),
    )
    db = factory()
    try:
        identity = db.query(AudienceExternalIdentity).filter_by(source_namespace="social", identity_type="account", normalized_reference="rollback-race").one()
        assert identity.subject_id in {item.id for item in db.query(AudienceSubject).all()}
        # The losing nested insert is rolled back: every remaining subject owns one identity.
        assert db.query(AudienceSubject).count() == db.query(AudienceExternalIdentity).count()
        assert sorted(item[0] for item in outcomes) in (["ok", "ok"], ["ok", "rejected"])
    finally:
        db.close()


def test_observation_evidence_outer_transaction_atomicity_and_schema_inventory(factory, engine):
    db = factory()
    try:
        service = AudienceFoundationService(db)
        observation = _observation(service, external_id="atomic")
        service.record_evidence(observation_id=observation.id, source_reference="atomic", normalized_representation={"text": "same"}, content_fingerprint="d" * 64)
        with pytest.raises(ValueError):
            service.record_evidence(observation_id=observation.id, source_reference="atomic", source_uri="https://conflict.test", normalized_representation={"text": "same"}, content_fingerprint="d" * 64)
        db.rollback()
    finally:
        db.close()
    verify = factory()
    try:
        assert verify.query(AudienceObservation).filter_by(source_reference="https://example.test/atomic").count() == 0
        assert verify.query(AudienceEvidence).count() == 0
    finally:
        verify.close()

    inspector = inspect(engine)
    assert "ck_audience_subjects_type" in {item["name"] for item in inspector.get_check_constraints("audience_subjects")}
    assert "uq_audience_research_runs_idempotency_key" in {item["name"] for item in inspector.get_unique_constraints("audience_research_runs")}
    assert "uq_audience_external_identity_reference" in {item["name"] for item in inspector.get_unique_constraints("audience_external_identities")}
    assert "uq_audience_observations_key" in {item["name"] for item in inspector.get_unique_constraints("audience_observations")}
    assert "uq_audience_evidence_observation_fingerprint" in {item["name"] for item in inspector.get_unique_constraints("audience_evidence")}
    assert {"ix_audience_external_identities_subject_id", "ix_audience_external_identities_namespace_type"} <= {item["name"] for item in inspector.get_indexes("audience_external_identities")}
    assert {"ix_audience_observations_research_run_id", "ix_audience_observations_subject_id", "ix_audience_observations_source_namespace_type", "ix_audience_observations_observed_at"} <= {item["name"] for item in inspector.get_indexes("audience_observations")}
    assert "ix_audience_evidence_observation_id" in {item["name"] for item in inspector.get_indexes("audience_evidence")}
    assert all((item.get("options") or {}).get("ondelete") is None for item in inspector.get_foreign_keys("audience_observations"))
