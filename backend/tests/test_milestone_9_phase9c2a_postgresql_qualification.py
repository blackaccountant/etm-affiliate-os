"""Guarded, real-PostgreSQL qualification for M9C2A serialization and authority rules."""

import os
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.crm.contracts import ContactPointProvenanceInput, ContactPointStateEventInput, SuppressionEventInput
from app.outreach.cold_b2b_contracts import CreateColdProspectingAuthorizationRequest, OrganizationEvidenceAuthorityReference, PolicySelectionAuthorityReference
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.repositories.cold_prospecting_repository import ColdProspectingRepository, advisory_lock_key
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.cold_prospecting_authority_registration_service import ColdProspectingAuthorityRegistrationService
from app.services.cold_prospecting_authorization_service import ColdProspectingAuthorizationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService
from app.services.suppression_service import SuppressionService

HEAD, PRIOR = "c2d3e4f5a6b7", "c1d2e3f4a5b6"
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
RAW = os.getenv("ETM_G5_DATABASE_URL")
if not RAW:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
URL = make_url(RAW)
if not (URL.drivername.startswith("postgresql") and URL.database == "etm_g5_m9c2a_qualification"):
    raise RuntimeError("M9C2A permits only ETM_G5_DATABASE_URL for etm_g5_m9c2a_qualification.")


@pytest.fixture(scope="module")
def engine():
    previous = settings.DATABASE_URL
    settings.DATABASE_URL = URL.render_as_string(hide_password=False)
    result = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        command.upgrade(Config("alembic.ini"), HEAD)
        yield result
    finally:
        settings.DATABASE_URL = previous
        result.dispose()


@pytest.fixture
def factory(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE cold_prospecting_authorizations, cold_prospecting_policy_selections, cold_prospecting_organization_evidence CASCADE"))
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _seed(factory):
    db = factory()
    try:
        subject = AudienceFoundationService(db).create_subject("ORGANIZATION")
        lead = LeadService(db).create_or_reuse(subject.id).record
        point = ContactPointService(db).create_or_reuse(lead.id, kind="EMAIL", normalized_value=f"{uuid4().hex}@example.com").record
        ContactPointService(db).append_state_event(point.id, ContactPointStateEventInput("ACTIVE", "VERIFIED", NOW, "pg", uuid4().hex))
        ContactPointService(db).attach_provenance(point.id, ContactPointProvenanceInput("PUBLIC_BUSINESS_SOURCE", "pg", uuid4().hex, NOW, NOW, evidence_fingerprint="a" * 64))
        register = ColdProspectingAuthorityRegistrationService(db)
        organization, _ = register.register_organization_evidence(lead_id=lead.id, source_namespace="pg-org", source_event_key=sha256_fingerprint({"org": uuid4().hex}), source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="b" * 64, evidence_fingerprint="c" * 64, evaluated_at=NOW)
        policy, _ = register.register_policy_selection(lead_id=lead.id, source_namespace="pg-policy", source_event_key=sha256_fingerprint({"policy": uuid4().hex}), evidence_fingerprint="d" * 64, profile_key="cold-b2b-default-v1", evaluated_at=NOW)
        db.commit()
        return lead.id, point.id, organization.id, organization.evidence_fingerprint, policy.id, policy.decision_fingerprint
    finally:
        db.close()


def _request(seed, source=None, *, purpose="cold_b2b:hosting", action="INITIAL", at=NOW):
    lead, point, organization, org_fp, policy, policy_fp = seed
    return CreateColdProspectingAuthorizationRequest(lead, point, purpose, action, "pg-cold", sha256_fingerprint({"authorization": source or uuid4().hex}), OrganizationEvidenceAuthorityReference(organization, org_fp), PolicySelectionAuthorityReference(policy, policy_fp), "e" * 64, at)


def _source_key(source):
    return sha256_fingerprint({"authorization": source})


def _authorize(factory, request, outcomes, errors, start):
    db = factory()
    try:
        db.connection(execution_options={"isolation_level": "READ COMMITTED"})
        start.wait(timeout=15)
        record, reused = ColdProspectingAuthorizationService(db).create_or_reuse(request)
        db.commit()
        outcomes.append((record.id, record.authorization_state, tuple(record.reason_codes), reused))
    except Exception as error:
        db.rollback(); errors.append(error)
    finally:
        db.close()


def _concurrent(factory, requests):
    outcomes, errors, start = [], [], threading.Barrier(len(requests) + 1)
    threads = [threading.Thread(target=_authorize, args=(factory, request, outcomes, errors, start)) for request in requests]
    for thread in threads: thread.start()
    start.wait(timeout=15)
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    return outcomes, errors


def test_requires_read_committed_not_repeatable_read(factory):
    db = factory()
    try:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        with pytest.raises(OutreachError, match="READ COMMITTED") as error:
            ColdProspectingAuthorizationService(db).create_or_reuse(_request(_seed(factory)))
        assert error.value.category == "ISOLATION_REQUIRED"
    finally:
        db.rollback(); db.close()


def test_post_lock_visibility_sees_committed_initial(factory, monkeypatch):
    seed = _seed(factory)
    a_ready, b_source_locked, release_a = threading.Event(), threading.Event(), threading.Event()
    outcomes, errors = [], []
    original = ColdProspectingRepository.acquire_lock
    def observed_lock(repo, namespace, identity):
        original(repo, namespace, identity)
        if namespace == "cold-source-v1" and identity.endswith("\x00" + _source_key("post-lock-b")): b_source_locked.set()
    monkeypatch.setattr(ColdProspectingRepository, "acquire_lock", observed_lock)
    def worker(name, source, hold=False):
        db = factory()
        try:
            db.connection(execution_options={"isolation_level": "READ COMMITTED"})
            record, _ = ColdProspectingAuthorizationService(db).create_or_reuse(_request(seed, source))
            if hold:
                a_ready.set(); assert release_a.wait(15)
            db.commit(); outcomes.append((name, record.authorization_state, tuple(record.reason_codes)))
        except Exception as error:
            db.rollback(); errors.append(error)
        finally: db.close()
    first = threading.Thread(target=worker, args=("a", "post-lock-a", True)); first.start(); assert a_ready.wait(15)
    second = threading.Thread(target=worker, args=("b", "post-lock-b")); second.start(); assert b_source_locked.wait(15)
    release_a.set(); first.join(30); second.join(30)
    assert errors == [] and not first.is_alive() and not second.is_alive()
    assert dict((name, state) for name, state, _ in outcomes) == {"a": "ELIGIBLE", "b": "INELIGIBLE"}
    assert "INITIAL_ALREADY_AUTHORIZED" in next(reasons for name, _, reasons in outcomes if name == "b")


def test_identical_and_conflicting_concurrent_replay(factory):
    seed = _seed(factory); request = _request(seed, "same-source")
    outcomes, errors = _concurrent(factory, (request, request))
    assert errors == [] and len(outcomes) == 2 and len({item[0] for item in outcomes}) == 1 and sorted(item[3] for item in outcomes) == [False, True]
    seed = _seed(factory)
    outcomes, errors = _concurrent(factory, (_request(seed, "conflict"), _request(seed, "conflict", purpose="cold_b2b:other")))
    assert len(outcomes) == 1 and outcomes[0][1] == "ELIGIBLE"
    assert len(errors) == 1 and isinstance(errors[0], OutreachError) and errors[0].category == "IDEMPOTENCY_CONFLICT"


def test_concurrent_initial_and_final_follow_up_have_one_eligible(factory):
    seed = _seed(factory)
    outcomes, errors = _concurrent(factory, (_request(seed, "initial-a"), _request(seed, "initial-b")))
    assert errors == [] and [state for _, state, _, _ in outcomes].count("ELIGIBLE") == 1
    seed = _seed(factory); db = factory()
    try:
        service = ColdProspectingAuthorizationService(db)
        service.create_or_reuse(_request(seed, "initial"))
        service.create_or_reuse(_request(seed, "follow-1", action="FOLLOW_UP", at=NOW + timedelta(days=7)))
        service.create_or_reuse(_request(seed, "follow-2", action="FOLLOW_UP", at=NOW + timedelta(days=14)))
        db.commit()
    finally: db.close()
    outcomes, errors = _concurrent(factory, (_request(seed, "final-a", action="FOLLOW_UP", at=NOW + timedelta(days=21)), _request(seed, "final-b", action="FOLLOW_UP", at=NOW + timedelta(days=21))))
    assert errors == [] and [state for _, state, _, _ in outcomes].count("ELIGIBLE") == 1
    assert any("FOLLOW_UP_LIMIT_REACHED" in reasons for _, _, reasons, _ in outcomes)


def test_spacing_and_frequency_are_partitioned_by_purpose_family(factory):
    seed = _seed(factory); db = factory()
    try:
        service = ColdProspectingAuthorizationService(db)
        initial, _ = service.create_or_reuse(_request(seed, "hosting-initial"))
        too_soon, _ = service.create_or_reuse(_request(seed, "hosting-soon", action="FOLLOW_UP", at=NOW + timedelta(days=6, seconds=86399)))
        other, _ = service.create_or_reuse(_request(seed, "platform-initial", purpose="cold_b2b:platform", at=NOW + timedelta(days=1)))
        db.commit()
        assert initial.authorization_state == other.authorization_state == "ELIGIBLE"
        assert too_soon.authorization_state == "INELIGIBLE" and "FOLLOW_UP_SPACING_NOT_MET" in too_soon.reason_codes
    finally: db.close()


def test_committed_and_concurrently_committed_suppression_blocks(factory, monkeypatch):
    seed = _seed(factory); db = factory()
    try:
        SuppressionService(db).append(seed[0], SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", NOW, "pg", uuid4().hex)); db.commit()
    finally: db.close()
    db = factory()
    try:
        record, _ = ColdProspectingAuthorizationService(db).create_or_reuse(_request(seed, "committed-suppression"))
        assert record.authorization_state == "INELIGIBLE" and "SUPPRESSED_GLOBAL" in record.reason_codes; db.commit()
    finally: db.close()
    seed = _seed(factory); source_locked, continue_read = threading.Event(), threading.Event()
    original = ColdProspectingRepository.acquire_lock
    def pause_after_source(repo, namespace, identity):
        original(repo, namespace, identity)
        if namespace == "cold-source-v1" and identity.endswith("\x00" + _source_key("concurrent-suppression")):
            source_locked.set(); assert continue_read.wait(15)
    monkeypatch.setattr(ColdProspectingRepository, "acquire_lock", pause_after_source)
    outcomes, errors = [], []
    worker = threading.Thread(target=_authorize, args=(factory, _request(seed, "concurrent-suppression"), outcomes, errors, threading.Barrier(1)))
    worker.start(); assert source_locked.wait(15)
    writer = factory()
    try:
        SuppressionService(writer).append(seed[0], SuppressionEventInput("GLOBAL_LEAD", "APPLIED", "COMPLAINT", NOW, "pg", uuid4().hex)); writer.commit()
    finally: writer.close()
    continue_read.set(); worker.join(30)
    assert errors == [] and outcomes[0][1] == "INELIGIBLE" and "SUPPRESSED_GLOBAL" in outcomes[0][2]


def test_advisory_lock_order_and_release(factory, monkeypatch, engine):
    seed = _seed(factory); observed = []; original = ColdProspectingRepository.acquire_lock
    def traced(repo, namespace, identity):
        observed.append(namespace); return original(repo, namespace, identity)
    monkeypatch.setattr(ColdProspectingRepository, "acquire_lock", traced)
    db = factory()
    try: ColdProspectingAuthorizationService(db).create_or_reuse(_request(seed, "lock-order")); db.commit()
    finally: db.close()
    assert observed == ["cold-source-v1", "cold-frequency-v1"]
    key = advisory_lock_key("cold-source-v1", "pg-cold\x00" + _source_key("lock-order"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}).scalar_one() is True
        connection.rollback()


def test_append_only_owner_constraints_and_pii_guards(factory, engine):
    seed = _seed(factory); db = factory()
    try: record, _ = ColdProspectingAuthorizationService(db).create_or_reuse(_request(seed, "append-only")); db.commit()
    finally: db.close()
    other_seed = _seed(factory)
    identifiers = {"cold_prospecting_organization_evidence": seed[2], "cold_prospecting_policy_selections": seed[4], "cold_prospecting_authorizations": record.id}
    with engine.connect() as connection:
        for table, identifier in identifiers.items():
            with pytest.raises(Exception): connection.execute(text(f"UPDATE {table} SET recorded_at=recorded_at WHERE id=:id"), {"id": identifier})
            connection.rollback()
    pairs = {(tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspect(engine).get_foreign_keys("cold_prospecting_authorizations")}
    assert (("organization_evidence_id", "lead_id"), "cold_prospecting_organization_evidence", ("id", "lead_id")) in pairs
    assert (("policy_selection_id", "lead_id"), "cold_prospecting_policy_selections", ("id", "lead_id")) in pairs
    clone = """INSERT INTO cold_prospecting_authorizations (id, lead_id, contact_point_id, organization_evidence_id, policy_selection_id, channel, purpose_key, purpose_family, requested_action, source_namespace, source_event_key, request_fingerprint, authorization_state, reason_codes, eligibility_policy_version, frequency_policy_version, policy_profile_key, decision_fingerprint, evidence, evaluated_at, recorded_at)
    SELECT :id, lead_id, contact_point_id, :organization_evidence_id, :policy_selection_id, channel, purpose_key, purpose_family, requested_action, source_namespace, :source_event_key, request_fingerprint, authorization_state, reason_codes, eligibility_policy_version, frequency_policy_version, policy_profile_key, decision_fingerprint, evidence, evaluated_at, recorded_at FROM cold_prospecting_authorizations WHERE id=:record_id"""
    with engine.connect() as connection:
        with pytest.raises(Exception): connection.execute(text(clone), {"id": str(uuid4()), "organization_evidence_id": other_seed[2], "policy_selection_id": seed[4], "source_event_key": sha256_fingerprint({"cross": "organization"}), "record_id": record.id})
        connection.rollback()
        with pytest.raises(Exception): connection.execute(text(clone), {"id": str(uuid4()), "organization_evidence_id": seed[2], "policy_selection_id": other_seed[4], "source_event_key": sha256_fingerprint({"cross": "policy"}), "record_id": record.id})
        connection.rollback()
    registration_db = factory()
    try:
        with pytest.raises(OutreachError): ColdProspectingAuthorityRegistrationService(registration_db).register_organization_evidence(lead_id=seed[0], source_namespace="pii", source_event_key="person@example.com", source_classification="ORGANIZATION_REGISTRY", source_record_fingerprint="person@example.com", evidence_fingerprint="a" * 64, evaluated_at=NOW)
    finally: registration_db.close()
    with pytest.raises(OutreachError): _request(seed, "pii-purpose", purpose="cold_b2b:person@example.com")


def test_migration_round_trip(engine):
    config = Config("alembic.ini")
    command.downgrade(config, PRIOR)
    with engine.connect() as connection: assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PRIOR
    assert "cold_prospecting_policy_selections" not in inspect(engine).get_table_names()
    command.upgrade(config, HEAD)
    with engine.connect() as connection: assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
    assert "cold_prospecting_policy_selections" in inspect(engine).get_table_names()
