"""M9C2B successor-compatible additive migration proof."""

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect


REVISION, PREVIOUS = "d3e4f5a6b7c8", "c2d3e4f5a6b7"
TABLES = {"cold_delivery_operations", "cold_message_contents", "cold_delivery_operation_state", "cold_delivery_events", "cold_t3_decisions", "cold_provider_dispatches", "cold_provider_dispatch_references", "cold_provider_feedback_receipts"}


def module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_cold_delivery_persistence.py"
    spec = importlib.util.spec_from_file_location("m9c2b_migration", path); value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def test_revision_is_single_head_and_exact_successor():
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    assert scripts.get_heads() == [REVISION] and scripts.get_revision(REVISION).down_revision == PREVIOUS


def test_additive_roundtrip_constraints_and_no_routing_pii():
    engine = create_engine("sqlite://"); migration = module()
    try:
        with engine.begin() as connection:
            metadata = sa.MetaData()
            sa.Table("crm_leads", metadata, sa.Column("id", sa.String(36), primary_key=True))
            sa.Table("crm_contact_points", metadata, sa.Column("id", sa.String(36), primary_key=True))
            sa.Table("cold_prospecting_authorizations", metadata, sa.Column("id", sa.String(36), primary_key=True), sa.Column("lead_id", sa.String(36), nullable=False), sa.Column("contact_point_id", sa.String(36), nullable=False), sa.UniqueConstraint("id", "lead_id", "contact_point_id"))
            metadata.create_all(connection); migration.op = Operations(MigrationContext.configure(connection)); migration.upgrade()
            inspector = inspect(connection); assert TABLES.issubset(set(inspector.get_table_names()))
            assert ("cold_authorization_id",) in {tuple(item["column_names"]) for item in inspector.get_unique_constraints("cold_delivery_operations")}
            assert ("operation_id", "sequence_number") in {tuple(item["column_names"]) for item in inspector.get_unique_constraints("cold_delivery_events")}
            assert ("provider_key", "provider_operation_key") in {tuple(item["column_names"]) for item in inspector.get_unique_constraints("cold_provider_dispatches")}
            assert ("provider_key", "provider_event_key") in {tuple(item["column_names"]) for item in inspector.get_unique_constraints("cold_provider_feedback_receipts")}
            columns = {item["name"] for table in TABLES - {"cold_message_contents"} for item in inspector.get_columns(table)}
            assert not {"recipient", "recipient_email", "normalized_value", "body", "secret", "api_key"}.intersection(columns)
            migration.downgrade(); assert not TABLES.intersection(set(inspect(connection).get_table_names()))
    finally: engine.dispose()
