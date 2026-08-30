"""Guarded real-PostgreSQL concurrency and isolation proofs for M8E."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.crm.contact_normalization_contracts import ContactNormalizationCandidate
from app.crm.contracts import (
    CRMError,
    ContactPointProvenanceInput,
    ContactPointStateEventInput,
    PermissionEventInput,
    SuppressionEventInput,
)
from app.crm.lifecycle_contracts import LifecycleTransitionRequest
from app.models.audience import AudienceProfile, AudienceQualificationAssessment
from app.models.crm import (
    ContactPoint,
    ContactPointProvenance,
    ContactPointStateEvent,
    Lead,
    PermissionEvent,
    SuppressionEvent,
)
from app.models.crm_relationships import LeadLifecycleEvent, LeadQualificationLink
from app.repositories.contact_point_repository import ContactPointRepository
from app.repositories.lead_lifecycle_repository import LeadLifecycleRepository
from app.repositories.lead_qualification_repository import LeadQualificationRepository
from app.repositories.permission_repository import PermissionRepository
from app.repositories.suppression_repository import SuppressionRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_registration_service import ContactPointRegistrationService
from app.services.contact_point_service import ContactPointService
from app.services.contactability_evaluation_service import ContactabilityEvaluationService
from app.services.lead_lifecycle_service import LeadLifecycleService
from app.services.lead_qualification_link_service import LeadQualificationLinkService
from app.services.lead_service import LeadService
from app.services.permission_service import PermissionService
from app.services.suppression_service import SuppressionService


HEAD = "f0a1b2c3d4e5"
BACKEND_ROOT = Path(__file__).parents[1]
DOMAIN_TIME = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
EVALUATED_AS_OF = DOMAIN_TIME + timedelta(days=1)
PURPOSE = "affiliate-marketing"
DIMENSIONS = (
    "problem_strength",
    "interest_alignment",
    "research_intent",
    "comparison_intent",
    "evaluation_intent",
    "pricing_intent",
    "purchase_request_intent",
    "purchase_signal",
    "engagement",
    "business_need_fit",
)


_raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not _raw_url:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw_url)
if not (
    _url.drivername.startswith("postgresql")
    and _url.host == "127.0.0.1"
    and _url.database == "etm_affiliate_os_g5_test"
):
    raise RuntimeError("M8E permits only the exact guarded local G5 database.")


def _database_url() -> str:
    return _url.render_as_string(hide_password=False)


@contextmanager
def _guarded_alembic():
    previous = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = _database_url()
        yield Config(str(BACKEND_ROOT / "alembic.ini"))
    finally:
        settings.DATABASE_URL = previous


def _revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with _guarded_alembic() as config:
            command.upgrade(config, HEAD)
        assert _revision(engine) == HEAD
        yield engine
        assert engine.pool.checkedout() == 0
    finally:
        try:
            with _guarded_alembic() as config:
                command.upgrade(config, HEAD)
            assert _revision(engine) == HEAD
        finally:
            engine.dispose()


@pytest.fixture
def pg_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _run_two(factory, operations):
    start = threading.Barrier(3)
    lock = threading.Lock()
    results, errors, pids = [], [], []

    def worker(index):
        db = factory()
        try:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = db.execute(text("SELECT pg_backend_pid()")) .scalar_one()
            with lock:
                pids.append(pid)
            start.wait(timeout=10)
            result = operations[index](db)
            assert db.in_transaction()
            db.commit()
            with lock:
                results.append((index, result))
        except BaseException as error:  # captured for deterministic parent-thread assertions
            db.rollback()
            with lock:
                errors.append((index, error))
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(index,), daemon=True) for index in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads), "PostgreSQL race worker exceeded timeout"
    assert len(pids) == 2 and pids[0] != pids[1]
    return results, errors, pids


def _install_contention_barrier(monkeypatch, owner, method_name, original=None):
    original = original or getattr(owner, method_name)
    barrier = threading.Barrier(2)

    def synchronized(self, *args, **kwargs):
        barrier.wait(timeout=10)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method_name, synchronized)
    return original


def _assert_no_integrity(errors):
    assert not any(isinstance(error, IntegrityError) for _, error in errors)


def _seed_leads(factory, count=1):
    db = factory()
    values = []
    try:
        for index in range(count):
            subject = AudienceFoundationService(db).create_subject("PERSON" if index == 0 else "ORGANIZATION")
            lead = LeadService(db).create_or_reuse(subject.id).record
            values.append((subject.id, lead.id))
        db.commit()
        return values
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _seed_contact(factory):
    subject_id, lead_id = _seed_leads(factory)[0]
    db = factory()
    try:
        token = uuid4().hex
        contact = ContactPointService(db).create_or_reuse(
            lead_id, kind="EMAIL", normalized_value=f"{token}@example.com"
        ).record
        db.commit()
        return subject_id, lead_id, contact.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _seed_assessment(factory):
    subject_id, lead_id = _seed_leads(factory)[0]
    db = factory()
    try:
        token = uuid4().hex
        profile = AudienceProfile(
            subject_id=subject_id,
            profile_ruleset_version=f"m8e-{token}",
            source_fingerprint=(token * 2)[:64],
            effective_as_of=DOMAIN_TIME,
            summary_json={"m8e": True},
        )
        db.add(profile)
        db.flush()
        assessment = AudienceQualificationAssessment(
            profile_id=profile.id,
            scoring_ruleset_version=f"m8e-{token}",
            scoring_ruleset_fingerprint=("a" + token * 2)[:64],
            scoring_ruleset_json={"m8e": True},
            context_type="NONE",
            context_json={},
            context_fingerprint=("b" + token * 2)[:64],
            selected_membership_fingerprint=("c" + token * 2)[:64],
            intent_score=60,
            qualification_score=60,
            qualification_status="QUALIFIED",
            derived_at=DOMAIN_TIME,
            **{field: 60 for field in DIMENSIONS},
        )
        db.add(assessment)
        db.commit()
        return subject_id, lead_id, profile.id, assessment.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _initialize_lead(factory, lead_id, namespace):
    db = factory()
    try:
        result = LeadLifecycleService(db).transition(
            lead_id,
            LifecycleTransitionRequest("DISCOVERED", DOMAIN_TIME, namespace, "discovered"),
        )
        db.commit()
        return result.event_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _cleanup_subjects(engine, subject_ids):
    with engine.begin() as connection:
        for subject_id in subject_ids:
            params = {"subject_id": subject_id}
            leads = "SELECT id FROM crm_leads WHERE subject_id=:subject_id"
            contacts = f"SELECT id FROM crm_contact_points WHERE lead_id IN ({leads})"
            profiles = "SELECT id FROM audience_profiles WHERE subject_id=:subject_id"
            assessments = f"SELECT id FROM audience_qualification_assessments WHERE profile_id IN ({profiles})"
            connection.execute(text(f"DELETE FROM crm_lead_lifecycle_events WHERE lead_id IN ({leads})"), params)
            connection.execute(text(f"DELETE FROM crm_lead_qualification_links WHERE lead_id IN ({leads})"), params)
            connection.execute(text(f"DELETE FROM crm_suppression_events WHERE lead_id IN ({leads})"), params)
            connection.execute(text(f"DELETE FROM crm_permission_events WHERE contact_point_id IN ({contacts})"), params)
            connection.execute(text(f"DELETE FROM crm_contact_point_state_events WHERE contact_point_id IN ({contacts})"), params)
            connection.execute(text(f"DELETE FROM crm_contact_point_provenance WHERE contact_point_id IN ({contacts})"), params)
            connection.execute(text(f"DELETE FROM crm_contact_points WHERE lead_id IN ({leads})"), params)
            connection.execute(text(f"DELETE FROM crm_leads WHERE subject_id=:subject_id"), params)
            connection.execute(text(f"DELETE FROM audience_qualification_contributions WHERE assessment_id IN ({assessments})"), params)
            connection.execute(text(f"DELETE FROM audience_qualification_assessment_memberships WHERE assessment_id IN ({assessments})"), params)
            connection.execute(text(f"DELETE FROM audience_qualification_assessments WHERE profile_id IN ({profiles})"), params)
            connection.execute(text(f"DELETE FROM audience_profile_signals WHERE profile_id IN ({profiles})"), params)
            connection.execute(text("DELETE FROM audience_profiles WHERE subject_id=:subject_id"), params)
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:subject_id"), params)


def _provenance(namespace, key):
    return ContactPointProvenanceInput(
        source_type="MANUAL",
        source_namespace=namespace,
        source_event_id=key,
        observed_at=DOMAIN_TIME,
    )


def _state(namespace, key, state="ACTIVE", verification="VERIFIED"):
    return ContactPointStateEventInput(
        state=state,
        verification_state=verification,
        occurred_at=DOMAIN_TIME,
        source_namespace=namespace,
        source_event_key=key,
    )


def _permission(namespace, key, event_type="CONSENTED"):
    return PermissionEventInput(
        channel="EMAIL",
        purpose_key=PURPOSE,
        event_type=event_type,
        occurred_at=DOMAIN_TIME,
        source_namespace=namespace,
        source_event_key=key,
    )


def _suppression(namespace, key, action="APPLIED"):
    return SuppressionEventInput(
        scope="GLOBAL_LEAD",
        action=action,
        reason="MANUAL",
        effective_at=DOMAIN_TIME + timedelta(hours=1),
        source_namespace=namespace,
        source_event_key=key,
    )


def test_postgresql_contact_registration_same_owner_converges(pg_factory, pg_engine, monkeypatch):
    subject_id, lead_id = _seed_leads(pg_factory)[0]
    token = uuid4().hex
    namespace = f"m8e-contact-same-{token}"
    original = _install_contention_barrier(monkeypatch, ContactPointRepository, "create_or_reuse")
    candidates = (
        ContactNormalizationCandidate("EMAIL", f"  Mailbox@Example{token}.COM  "),
        ContactNormalizationCandidate("EMAIL", f"Mailbox@example{token}.com"),
    )
    try:
        operations = tuple(
            lambda db, index=index: ContactPointRegistrationService(db).register(
                lead_id,
                candidates[index],
                _provenance(namespace, "shared-provenance"),
                _state(namespace, "shared-state"),
            )
            for index in range(2)
        )
        results, errors, _ = _run_two(pg_factory, operations)
        _assert_no_integrity(errors)
        assert errors == [] and len(results) == 2
        values = [result for _, result in results]
        assert len({value.contact_point_id for value in values}) == 1
        assert len({value.provenance_id for value in values}) == 1
        assert len({value.state_event_id for value in values}) == 1
        assert sorted(value.reused for value in values) == [False, True]
        verifier = pg_factory()
        try:
            contact_id = values[0].contact_point_id
            assert verifier.query(ContactPoint).filter_by(
                kind="EMAIL", normalized_value=f"Mailbox@example{token}.com"
            ).count() == 1
            assert verifier.query(ContactPointProvenance).filter_by(contact_point_id=contact_id).count() == 1
            assert verifier.query(ContactPointStateEvent).filter_by(contact_point_id=contact_id).count() == 1
            assert verifier.query(Lead).filter_by(subject_id=subject_id).count() == 1
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(ContactPointRepository, "create_or_reuse", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_contact_registration_cross_owner_is_typed(pg_factory, pg_engine, monkeypatch):
    seeded = _seed_leads(pg_factory, 2)
    subject_ids = [item[0] for item in seeded]
    lead_ids = [item[1] for item in seeded]
    token = uuid4().hex
    namespace = f"m8e-contact-owner-{token}"
    original = _install_contention_barrier(monkeypatch, ContactPointRepository, "create_or_reuse")
    candidate = ContactNormalizationCandidate("EMAIL", f"owner-{token}@example.com")
    try:
        operations = tuple(
            lambda db, index=index: ContactPointRegistrationService(db).register(
                lead_ids[index], candidate, _provenance(namespace, f"owner-{index}")
            )
            for index in range(2)
        )
        results, errors, _ = _run_two(pg_factory, operations)
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError)
        assert errors[0][1].category == "CONTACT_POINT_OWNERSHIP_CONFLICT"
        verifier = pg_factory()
        try:
            contacts = verifier.query(ContactPoint).filter_by(
                kind="EMAIL", normalized_value=f"owner-{token}@example.com"
            ).all()
            assert len(contacts) == 1 and contacts[0].lead_id in lead_ids
            assert verifier.query(Lead).filter(Lead.id.in_(lead_ids)).count() == 2
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(ContactPointRepository, "create_or_reuse", original)
        _cleanup_subjects(pg_engine, subject_ids)


def test_postgresql_qualification_link_race_converges(pg_factory, pg_engine, monkeypatch):
    subject_id, lead_id, profile_id, assessment_id = _seed_assessment(pg_factory)
    original = _install_contention_barrier(monkeypatch, LeadQualificationRepository, "create_or_reuse")
    try:
        operations = (
            lambda db: LeadQualificationLinkService(db).link(lead_id, assessment_id),
            lambda db: LeadQualificationLinkService(db).link(lead_id, assessment_id),
        )
        results, errors, _ = _run_two(pg_factory, operations)
        _assert_no_integrity(errors)
        assert errors == [] and len(results) == 2
        values = [result for _, result in results]
        assert len({value.link_id for value in values}) == 1
        assert sorted(value.reused for value in values) == [False, True]
        verifier = pg_factory()
        try:
            assert verifier.query(LeadQualificationLink).filter_by(
                lead_id=lead_id, assessment_id=assessment_id
            ).count() == 1
            assert verifier.get(Lead, lead_id).subject_id == subject_id
            assessment = verifier.get(AudienceQualificationAssessment, assessment_id)
            assert (assessment.profile_id, assessment.qualification_status) == (profile_id, "QUALIFIED")
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(LeadQualificationRepository, "create_or_reuse", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_lifecycle_for_update_serializes_same_transition(pg_factory, pg_engine, monkeypatch):
    subject_id, lead_id = _seed_leads(pg_factory)[0]
    namespace = f"m8e-lifecycle-lock-{uuid4().hex}"
    _initialize_lead(pg_factory, lead_id, namespace)
    original = _install_contention_barrier(monkeypatch, LeadLifecycleRepository, "lock_lead")
    try:
        operations = tuple(
            lambda db, index=index: LeadLifecycleService(db).transition(
                lead_id,
                LifecycleTransitionRequest(
                    "ENRICHED", DOMAIN_TIME + timedelta(minutes=1), namespace, f"enriched-{index}"
                ),
            )
            for index in range(2)
        )
        results, errors, _ = _run_two(pg_factory, operations)
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError)
        assert errors[0][1].category == "INVALID_LIFECYCLE_TRANSITION"
        verifier = pg_factory()
        try:
            events = verifier.query(LeadLifecycleEvent).filter_by(lead_id=lead_id).order_by(
                LeadLifecycleEvent.sequence_number
            ).all()
            assert [event.sequence_number for event in events] == [1, 2]
            assert [(event.from_state, event.to_state) for event in events] == [
                (None, "DISCOVERED"), ("DISCOVERED", "ENRICHED")
            ]
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(LeadLifecycleRepository, "lock_lead", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_lifecycle_idempotency_races_are_typed(pg_factory, pg_engine, monkeypatch):
    seeded = _seed_leads(pg_factory, 2)
    subject_ids = [item[0] for item in seeded]
    identical_lead, conflict_lead = seeded[0][1], seeded[1][1]
    identical_ns = f"m8e-lifecycle-identical-{uuid4().hex}"
    conflict_ns = f"m8e-lifecycle-conflict-{uuid4().hex}"
    _initialize_lead(pg_factory, identical_lead, identical_ns)
    _initialize_lead(pg_factory, conflict_lead, conflict_ns)
    original = LeadLifecycleRepository.lock_lead
    try:
        _install_contention_barrier(monkeypatch, LeadLifecycleRepository, "lock_lead", original)
        request = LifecycleTransitionRequest(
            "ENRICHED", DOMAIN_TIME + timedelta(minutes=1), identical_ns, "shared"
        )
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: LeadLifecycleService(db).transition(identical_lead, request),
                lambda db: LeadLifecycleService(db).transition(identical_lead, request),
            ),
        )
        _assert_no_integrity(errors)
        assert errors == [] and len(results) == 2
        identical = [result for _, result in results]
        assert len({value.event_id for value in identical}) == 1
        assert sorted(value.reused for value in identical) == [False, True]

        _install_contention_barrier(monkeypatch, LeadLifecycleRepository, "lock_lead", original)
        conflicting = (
            LifecycleTransitionRequest(
                "ENRICHED", DOMAIN_TIME + timedelta(minutes=1), conflict_ns, "shared"
            ),
            LifecycleTransitionRequest(
                "ARCHIVED", DOMAIN_TIME + timedelta(minutes=2), conflict_ns, "shared"
            ),
        )
        results, errors, _ = _run_two(
            pg_factory,
            tuple(
                lambda db, index=index: LeadLifecycleService(db).transition(conflict_lead, conflicting[index])
                for index in range(2)
            ),
        )
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError) and errors[0][1].category == "IDEMPOTENCY_CONFLICT"
        verifier = pg_factory()
        try:
            assert verifier.query(LeadLifecycleEvent).filter_by(
                source_namespace=conflict_ns, source_event_key="shared"
            ).count() == 1
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(LeadLifecycleRepository, "lock_lead", original)
        _cleanup_subjects(pg_engine, subject_ids)


def test_postgresql_contact_state_event_idempotency_races(pg_factory, pg_engine, monkeypatch):
    subject_id, _, contact_id = _seed_contact(pg_factory)
    namespace = f"m8e-state-{uuid4().hex}"
    original = ContactPointRepository.append_state_event
    try:
        _install_contention_barrier(monkeypatch, ContactPointRepository, "append_state_event", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: ContactPointService(db).append_state_event(contact_id, _state(namespace, "same")),
                lambda db: ContactPointService(db).append_state_event(contact_id, _state(namespace, "same")),
            ),
        )
        _assert_no_integrity(errors)
        assert errors == [] and len({result.record.id for _, result in results}) == 1
        assert sorted(result.reused for _, result in results) == [False, True]

        _install_contention_barrier(monkeypatch, ContactPointRepository, "append_state_event", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: ContactPointService(db).append_state_event(
                    contact_id, _state(namespace, "conflict", "ACTIVE", "VERIFIED")
                ),
                lambda db: ContactPointService(db).append_state_event(
                    contact_id, _state(namespace, "conflict", "INVALID", "UNVERIFIED")
                ),
            ),
        )
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError) and errors[0][1].category == "IDEMPOTENCY_CONFLICT"
        verifier = pg_factory()
        try:
            assert verifier.query(ContactPointStateEvent).filter_by(
                source_namespace=namespace, source_event_key="conflict"
            ).count() == 1
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(ContactPointRepository, "append_state_event", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_permission_event_idempotency_races(pg_factory, pg_engine, monkeypatch):
    subject_id, _, contact_id = _seed_contact(pg_factory)
    namespace = f"m8e-permission-{uuid4().hex}"
    original = PermissionRepository.append
    try:
        _install_contention_barrier(monkeypatch, PermissionRepository, "append", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: PermissionService(db).append(contact_id, _permission(namespace, "same")),
                lambda db: PermissionService(db).append(contact_id, _permission(namespace, "same")),
            ),
        )
        _assert_no_integrity(errors)
        assert errors == [] and len({result.record.id for _, result in results}) == 1
        assert sorted(result.reused for _, result in results) == [False, True]

        _install_contention_barrier(monkeypatch, PermissionRepository, "append", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: PermissionService(db).append(
                    contact_id, _permission(namespace, "conflict", "CONSENTED")
                ),
                lambda db: PermissionService(db).append(
                    contact_id, _permission(namespace, "conflict", "REVOKED")
                ),
            ),
        )
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError) and errors[0][1].category == "IDEMPOTENCY_CONFLICT"
        verifier = pg_factory()
        try:
            rows = verifier.query(PermissionEvent).filter_by(
                source_namespace=namespace, source_event_key="conflict"
            ).all()
            assert len(rows) == 1 and (rows[0].contact_point_id, rows[0].channel, rows[0].purpose_key) == (
                contact_id, "EMAIL", PURPOSE
            )
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(PermissionRepository, "append", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_suppression_event_idempotency_races(pg_factory, pg_engine, monkeypatch):
    subject_id, lead_id = _seed_leads(pg_factory)[0]
    namespace = f"m8e-suppression-{uuid4().hex}"
    original = SuppressionRepository.append
    try:
        _install_contention_barrier(monkeypatch, SuppressionRepository, "append", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: SuppressionService(db).append(lead_id, _suppression(namespace, "same")),
                lambda db: SuppressionService(db).append(lead_id, _suppression(namespace, "same")),
            ),
        )
        _assert_no_integrity(errors)
        assert errors == [] and len({result.record.id for _, result in results}) == 1
        assert sorted(result.reused for _, result in results) == [False, True]

        _install_contention_barrier(monkeypatch, SuppressionRepository, "append", original)
        results, errors, _ = _run_two(
            pg_factory,
            (
                lambda db: SuppressionService(db).append(
                    lead_id, _suppression(namespace, "conflict", "APPLIED")
                ),
                lambda db: SuppressionService(db).append(
                    lead_id, _suppression(namespace, "conflict", "LIFTED")
                ),
            ),
        )
        _assert_no_integrity(errors)
        assert len(results) == 1 and len(errors) == 1
        assert isinstance(errors[0][1], CRMError) and errors[0][1].category == "IDEMPOTENCY_CONFLICT"
        verifier = pg_factory()
        try:
            rows = verifier.query(SuppressionEvent).filter_by(
                source_namespace=namespace, source_event_key="conflict"
            ).all()
            assert len(rows) == 1 and rows[0].lead_id == lead_id and rows[0].scope == "GLOBAL_LEAD"
        finally:
            verifier.close()
    finally:
        monkeypatch.setattr(SuppressionRepository, "append", original)
        _cleanup_subjects(pg_engine, [subject_id])


def test_postgresql_contactability_repeatable_read_snapshot(pg_factory, pg_engine):
    subject_id, lead_id, contact_id = _seed_contact(pg_factory)
    namespace = f"m8e-repeatable-read-{uuid4().hex}"
    setup = pg_factory()
    try:
        ContactPointService(setup).append_state_event(contact_id, _state(namespace, "state"))
        PermissionService(setup).append(contact_id, _permission(namespace, "permission"))
        setup.commit()
    except Exception:
        setup.rollback()
        raise
    finally:
        setup.close()

    connection_a = pg_engine.connect().execution_options(isolation_level="REPEATABLE READ")
    session_a = sessionmaker(bind=connection_a, autoflush=False, autocommit=False, expire_on_commit=False)()
    try:
        pid_a = session_a.execute(text("SELECT pg_backend_pid()")) .scalar_one()
        initial = ContactabilityEvaluationService(session_a).evaluate_point(
            lead_id,
            contact_id,
            channel="EMAIL",
            purpose_key=PURPOSE,
            evaluated_as_of=EVALUATED_AS_OF,
        )
        assert initial.state == "CONTACTABLE"

        session_b = pg_factory()
        try:
            pid_b = session_b.execute(text("SELECT pg_backend_pid()")) .scalar_one()
            assert pid_b != pid_a
            SuppressionService(session_b).append(lead_id, _suppression(namespace, "applied"))
            session_b.commit()
        except Exception:
            session_b.rollback()
            raise
        finally:
            session_b.close()

        repeated = ContactabilityEvaluationService(session_a).evaluate_point(
            lead_id,
            contact_id,
            channel="EMAIL",
            purpose_key=PURPOSE,
            evaluated_as_of=EVALUATED_AS_OF,
        )
        assert repeated.state == "CONTACTABLE"
        session_a.commit()
    finally:
        session_a.close()
        connection_a.close()

    verifier = pg_factory()
    try:
        fresh = ContactabilityEvaluationService(verifier).evaluate_point(
            lead_id,
            contact_id,
            channel="EMAIL",
            purpose_key=PURPOSE,
            evaluated_as_of=EVALUATED_AS_OF,
        )
        assert fresh.state == "NOT_CONTACTABLE"
        assert "SUPPRESSED_GLOBAL" in fresh.reason_codes
    finally:
        verifier.close()
        _cleanup_subjects(pg_engine, [subject_id])
    assert pg_engine.pool.checkedout() == 0
