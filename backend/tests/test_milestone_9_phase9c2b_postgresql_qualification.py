"""Guarded PostgreSQL proof for M9C2B immutable facts and mutable control state."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.cold_delivery import ColdDeliveryOperation, ColdDeliveryOperationState, ColdMessageContent
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.contact_point_service import ContactPointService
from app.services.lead_service import LeadService


HEAD, PRIOR = "d3e4f5a6b7c8", "c2d3e4f5a6b7"
NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
RAW = os.getenv("ETM_G5_DATABASE_URL")
if not RAW:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
URL = make_url(RAW)
if not (URL.drivername.startswith("postgresql") and URL.database == "etm_g5_m9c2b1_qualification"):
    raise RuntimeError("M9C2B permits only ETM_G5_DATABASE_URL for etm_g5_m9c2b1_qualification.")


@pytest.fixture(scope="module")
def engine():
    previous = settings.DATABASE_URL; settings.DATABASE_URL = URL.render_as_string(hide_password=False)
    result = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        command.upgrade(Config("alembic.ini"), HEAD); yield result
    finally:
        settings.DATABASE_URL = previous; result.dispose()


@pytest.fixture
def db(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE cold_provider_feedback_receipts, cold_provider_dispatch_references, cold_provider_dispatches, cold_t3_decisions, cold_delivery_events, cold_delivery_operation_state, cold_message_contents, cold_delivery_operations, cold_prospecting_authorizations CASCADE"))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try: yield session
    finally: session.close()


def _operation(db):
    subject = AudienceFoundationService(db).create_subject("ORGANIZATION")
    lead = LeadService(db).create_or_reuse(subject.id).record
    point = ContactPointService(db).create_or_reuse(lead.id, kind="EMAIL", normalized_value=f"m9c2b-{uuid4().hex}@example.com").record
    auth = ColdProspectingAuthorization(lead_id=lead.id, contact_point_id=point.id, organization_evidence_id=None, policy_selection_id=None, channel="EMAIL", purpose_key="cold_b2b:platform", purpose_family="platform", requested_action="INITIAL", source_namespace="m9c2b-pg", source_event_key="a" * 64, request_fingerprint="b" * 64, authorization_state="ELIGIBLE", reason_codes=["ELIGIBLE"], eligibility_policy_version="v1", frequency_policy_version="v1", policy_profile_key="profile", decision_fingerprint="c" * 64, evidence={}, evaluated_at=NOW)
    db.add(auth); db.flush()
    operation = ColdDeliveryOperation(cold_authorization_id=auth.id, lead_id=auth.lead_id, contact_point_id=auth.contact_point_id, action="INITIAL", purpose_key="cold_b2b:platform", purpose_family="platform", source_namespace="m9c2b-pg", source_event_key="d" * 64, message_content_fingerprint="e" * 64, operation_schema_version="v1", created_at=NOW)
    db.add(operation); db.flush(); db.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="CREATED", revision=1, next_event_sequence=1, updated_at=NOW)); db.commit(); return operation


def test_append_only_trigger_composite_content_fk_and_mutable_state(db, engine):
    operation = _operation(db)
    db.add(ColdMessageContent(operation_id=operation.id, content_fingerprint="e" * 64, subject=None, body="bounded content", content_format="TEXT", content_schema_version="v1", created_at=NOW)); db.commit()
    with engine.connect() as connection:
        with pytest.raises(Exception): connection.execute(text("UPDATE cold_delivery_operations SET purpose_family='changed' WHERE id=:id"), {"id": operation.id})
        connection.rollback()
        with pytest.raises(Exception): connection.execute(text("DELETE FROM cold_delivery_operations WHERE id=:id"), {"id": operation.id})
        connection.rollback()
        with pytest.raises(Exception): connection.execute(text("INSERT INTO cold_message_contents (id, operation_id, content_fingerprint, body, content_format, content_schema_version, created_at) VALUES ('f0000000-0000-0000-0000-000000000000', :id, :fingerprint, 'different', 'TEXT', 'v1', :now)"), {"id": operation.id, "fingerprint": "f" * 64, "now": NOW})
        connection.rollback()
        connection.execute(text("UPDATE cold_delivery_operation_state SET current_state='READY', revision=2 WHERE operation_id=:id"), {"id": operation.id}); connection.commit()
    db.expire_all(); assert db.get(ColdDeliveryOperationState, operation.id).current_state == "READY"


def test_migration_round_trip(engine):
    config = Config("alembic.ini")
    command.downgrade(config, PRIOR); command.upgrade(config, HEAD)
