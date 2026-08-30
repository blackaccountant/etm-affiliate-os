"""Guarded real-PostgreSQL migration and constraint proofs for M8E."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.audience import AudienceProfile, AudienceQualificationAssessment, AudienceSubject
from app.models.crm import (
    ContactPoint,
    ContactPointProvenance,
    ContactPointStateEvent,
    Lead,
    PermissionEvent,
    SuppressionEvent,
)
from app.models.crm_relationships import LeadLifecycleEvent, LeadQualificationLink


HEAD = "f0a1b2c3d4e5"
M8A = "e9f0a1b2c3d4"
M7A = "d8e9f0a1b2c3"
BACKEND_ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
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


def _config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


@contextmanager
def _guarded_alembic():
    previous = settings.DATABASE_URL
    try:
        settings.DATABASE_URL = _database_url()
        yield _config()
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
    finally:
        try:
            with _guarded_alembic() as config:
                command.upgrade(config, HEAD)
            assert _revision(engine) == HEAD
        finally:
            engine.dispose()


def test_postgresql_m8_alembic_graph_is_single_exact_chain():
    scripts = ScriptDirectory.from_config(_config())
    assert scripts.get_heads() == [HEAD]
    m8c = scripts.get_revision(HEAD)
    m8a = scripts.get_revision(M8A)
    assert m8c.down_revision == M8A
    assert m8a.down_revision == M7A


def test_postgresql_m8c_downgrade_reupgrade_preserves_prior_schema(pg_engine):
    m8a_tables = {
        "crm_leads",
        "crm_contact_points",
        "crm_contact_point_provenance",
        "crm_contact_point_state_events",
        "crm_permission_events",
        "crm_suppression_events",
    }
    m8c_tables = {"crm_lead_qualification_links", "crm_lead_lifecycle_events"}
    prior_tables = {"audience_subjects", "audience_qualification_assessments"}
    try:
        with _guarded_alembic() as config:
            command.upgrade(config, HEAD)
        assert _revision(pg_engine) == HEAD
        assert m8a_tables | m8c_tables | prior_tables <= set(inspect(pg_engine).get_table_names())

        with _guarded_alembic() as config:
            command.downgrade(config, M8A)
        assert _revision(pg_engine) == M8A
        downgraded_tables = set(inspect(pg_engine).get_table_names())
        assert not m8c_tables & downgraded_tables
        assert m8a_tables | prior_tables <= downgraded_tables
    finally:
        with _guarded_alembic() as config:
            command.upgrade(config, HEAD)
    assert _revision(pg_engine) == HEAD
    assert m8a_tables | m8c_tables | prior_tables <= set(inspect(pg_engine).get_table_names())


def test_postgresql_m8_constraint_catalog_matches_frozen_schema(pg_engine):
    inspector = inspect(pg_engine)

    def uniques(table):
        return {item["name"]: tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)}

    assert {
        "uq_crm_contact_points_identity": ("kind", "normalized_value"),
        "uq_crm_contact_points_id_lead": ("id", "lead_id"),
    }.items() <= uniques("crm_contact_points").items()
    assert {
        "uq_crm_contact_point_provenance_fingerprint": ("contact_point_id", "provenance_fingerprint"),
        "uq_crm_contact_point_provenance_source_event": (
            "contact_point_id", "source_namespace", "source_event_id"
        ),
    }.items() <= uniques("crm_contact_point_provenance").items()
    assert uniques("crm_contact_point_state_events")["uq_crm_contact_point_state_events_source"] == (
        "source_namespace", "source_event_key"
    )
    assert uniques("crm_permission_events")["uq_crm_permission_events_source"] == (
        "source_namespace", "source_event_key"
    )
    assert uniques("crm_suppression_events")["uq_crm_suppression_events_source"] == (
        "source_namespace", "source_event_key"
    )
    assert uniques("crm_lead_qualification_links")["uq_crm_lead_qualification_links_identity"] == (
        "lead_id", "assessment_id"
    )
    assert {
        "uq_crm_lead_lifecycle_events_sequence": ("lead_id", "sequence_number"),
        "uq_crm_lead_lifecycle_events_source": ("source_namespace", "source_event_key"),
    }.items() <= uniques("crm_lead_lifecycle_events").items()
    suppression_fks = {item["name"] for item in inspector.get_foreign_keys("crm_suppression_events")}
    assert "fk_crm_suppression_events_contact_owner" in suppression_fks
    suppression_checks = {item["name"] for item in inspector.get_check_constraints("crm_suppression_events")}
    assert {
        "ck_crm_suppression_events_scope_fields",
        "ck_crm_suppression_events_fingerprint",
        "ck_crm_suppression_events_source_key",
    } <= suppression_checks
    lifecycle_checks = {item["name"] for item in inspector.get_check_constraints("crm_lead_lifecycle_events")}
    assert {
        "ck_crm_lead_lifecycle_events_sequence",
        "ck_crm_lead_lifecycle_events_from_state",
        "ck_crm_lead_lifecycle_events_to_state",
        "ck_crm_lead_lifecycle_events_initialization",
        "ck_crm_lead_lifecycle_events_namespace",
        "ck_crm_lead_lifecycle_events_source_key",
        "ck_crm_lead_lifecycle_events_fingerprint",
    } <= lifecycle_checks


def _expect_constraint(db, record, constraint_name: str):
    with pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            db.add(record)
            db.flush()
    assert error.value.orig.diag.constraint_name == constraint_name
    assert db.in_transaction()


def test_postgresql_m8_critical_constraints_are_enforced_by_database(pg_engine):
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db = factory()
    token = uuid4().hex
    namespace = f"m8e-constraints-{token}"
    try:
        subject_a = AudienceSubject(subject_type="PERSON")
        subject_b = AudienceSubject(subject_type="ORGANIZATION")
        db.add_all((subject_a, subject_b))
        db.flush()
        lead_a = Lead(subject_id=subject_a.id)
        lead_b = Lead(subject_id=subject_b.id)
        db.add_all((lead_a, lead_b))
        db.flush()
        contact_a = ContactPoint(lead_id=lead_a.id, kind="EMAIL", normalized_value=f"{token}@example.com")
        contact_b = ContactPoint(lead_id=lead_b.id, kind="PHONE", normalized_value=f"+1555{token[:7]}")
        db.add_all((contact_a, contact_b))
        db.flush()
        provenance = ContactPointProvenance(
            contact_point_id=contact_a.id,
            source_type="MANUAL",
            source_namespace=namespace,
            source_event_id="provenance",
            provenance_fingerprint="a" * 64,
        )
        state = ContactPointStateEvent(
            contact_point_id=contact_a.id,
            state="ACTIVE",
            verification_state="VERIFIED",
            occurred_at=NOW,
            source_namespace=namespace,
            source_event_key="state",
            event_fingerprint="b" * 64,
        )
        permission = PermissionEvent(
            contact_point_id=contact_a.id,
            channel="EMAIL",
            purpose_key="affiliate-marketing",
            event_type="CONSENTED",
            occurred_at=NOW,
            source_namespace=namespace,
            source_event_key="permission",
            event_fingerprint="c" * 64,
        )
        suppression = SuppressionEvent(
            lead_id=lead_a.id,
            scope="GLOBAL_LEAD",
            channel=None,
            contact_point_id=None,
            action="APPLIED",
            reason="MANUAL",
            effective_at=NOW,
            source_namespace=namespace,
            source_event_key="suppression",
            event_fingerprint="d" * 64,
        )
        profile = AudienceProfile(
            subject_id=subject_a.id,
            profile_ruleset_version=f"m8e-{token}",
            source_fingerprint="e" * 64,
            effective_as_of=NOW,
            summary_json={"m8e": True},
        )
        db.add_all((provenance, state, permission, suppression, profile))
        db.flush()
        assessment = AudienceQualificationAssessment(
            profile_id=profile.id,
            scoring_ruleset_version=f"m8e-{token}",
            scoring_ruleset_fingerprint="f" * 64,
            scoring_ruleset_json={"m8e": True},
            context_type="NONE",
            context_json={},
            context_fingerprint="1" * 64,
            selected_membership_fingerprint="2" * 64,
            intent_score=60,
            qualification_score=60,
            qualification_status="QUALIFIED",
            derived_at=NOW,
            **{field: 60 for field in DIMENSIONS},
        )
        db.add(assessment)
        db.flush()
        link = LeadQualificationLink(lead_id=lead_a.id, assessment_id=assessment.id)
        lifecycle = LeadLifecycleEvent(
            lead_id=lead_a.id,
            sequence_number=1,
            from_state=None,
            to_state="DISCOVERED",
            occurred_at=NOW,
            source_namespace=namespace,
            source_event_key="lifecycle",
            event_fingerprint="3" * 64,
        )
        db.add_all((link, lifecycle))
        db.flush()

        _expect_constraint(
            db,
            ContactPoint(lead_id=lead_a.id, kind=contact_a.kind, normalized_value=contact_a.normalized_value),
            "uq_crm_contact_points_identity",
        )
        _expect_constraint(
            db,
            ContactPointProvenance(
                contact_point_id=contact_a.id,
                source_type="MANUAL",
                source_namespace=namespace,
                source_event_id="other-provenance",
                provenance_fingerprint=provenance.provenance_fingerprint,
            ),
            "uq_crm_contact_point_provenance_fingerprint",
        )
        _expect_constraint(
            db,
            ContactPointProvenance(
                contact_point_id=contact_a.id,
                source_type="MANUAL",
                source_namespace=namespace,
                source_event_id=provenance.source_event_id,
                provenance_fingerprint="4" * 64,
            ),
            "uq_crm_contact_point_provenance_source_event",
        )
        _expect_constraint(
            db,
            ContactPointStateEvent(
                contact_point_id=contact_a.id,
                state="INVALID",
                verification_state="UNVERIFIED",
                occurred_at=NOW,
                source_namespace=namespace,
                source_event_key=state.source_event_key,
                event_fingerprint="5" * 64,
            ),
            "uq_crm_contact_point_state_events_source",
        )
        _expect_constraint(
            db,
            PermissionEvent(
                contact_point_id=contact_a.id,
                channel="EMAIL",
                purpose_key="affiliate-marketing",
                event_type="REVOKED",
                occurred_at=NOW,
                source_namespace=namespace,
                source_event_key=permission.source_event_key,
                event_fingerprint="6" * 64,
            ),
            "uq_crm_permission_events_source",
        )
        _expect_constraint(
            db,
            SuppressionEvent(
                lead_id=lead_a.id,
                scope="GLOBAL_LEAD",
                action="LIFTED",
                reason="MANUAL",
                effective_at=NOW,
                source_namespace=namespace,
                source_event_key=suppression.source_event_key,
                event_fingerprint="7" * 64,
            ),
            "uq_crm_suppression_events_source",
        )
        _expect_constraint(
            db,
            SuppressionEvent(
                lead_id=lead_a.id,
                contact_point_id=contact_b.id,
                scope="CONTACT_POINT_CHANNEL",
                channel="SMS",
                action="APPLIED",
                reason="MANUAL",
                effective_at=NOW,
                source_namespace=namespace,
                source_event_key="wrong-owner",
                event_fingerprint="8" * 64,
            ),
            "fk_crm_suppression_events_contact_owner",
        )
        _expect_constraint(
            db,
            SuppressionEvent(
                lead_id=lead_a.id,
                scope="GLOBAL_LEAD",
                channel="EMAIL",
                action="APPLIED",
                reason="MANUAL",
                effective_at=NOW,
                source_namespace=namespace,
                source_event_key="bad-scope",
                event_fingerprint="9" * 64,
            ),
            "ck_crm_suppression_events_scope_fields",
        )
        _expect_constraint(
            db,
            LeadQualificationLink(lead_id=lead_a.id, assessment_id=assessment.id),
            "uq_crm_lead_qualification_links_identity",
        )
        _expect_constraint(
            db,
            LeadLifecycleEvent(
                lead_id=lead_a.id,
                sequence_number=1,
                from_state="DISCOVERED",
                to_state="ENRICHED",
                occurred_at=NOW,
                source_namespace=namespace,
                source_event_key="duplicate-sequence",
                event_fingerprint="a" * 64,
            ),
            "uq_crm_lead_lifecycle_events_sequence",
        )
        _expect_constraint(
            db,
            LeadLifecycleEvent(
                lead_id=lead_b.id,
                sequence_number=1,
                from_state=None,
                to_state="DISCOVERED",
                occurred_at=NOW,
                source_namespace=namespace,
                source_event_key=lifecycle.source_event_key,
                event_fingerprint="b" * 64,
            ),
            "uq_crm_lead_lifecycle_events_source",
        )
        _expect_constraint(
            db,
            LeadLifecycleEvent(
                lead_id=lead_b.id,
                sequence_number=1,
                from_state=None,
                to_state="ENRICHED",
                occurred_at=NOW,
                source_namespace=namespace,
                source_event_key="bad-initialization",
                event_fingerprint="c" * 64,
            ),
            "ck_crm_lead_lifecycle_events_initialization",
        )
    finally:
        db.rollback()
        db.close()
    assert pg_engine.pool.checkedout() == 0
