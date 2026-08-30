"""Structural and isolated roundtrip proof for the additive M9B migration."""

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect


REVISION = "b0c1d2e3f4a5"
PREVIOUS = "a0b1c2d3e4f5"
TABLES = {"outreach_delivery_attempts", "outreach_delivery_events"}
PRIOR_TABLES = {"crm_leads", "crm_contact_points", "outreach_intents", "outreach_messages"}


def _module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_outreach_delivery_attempt_events.py"
    spec = importlib.util.spec_from_file_location("m9b_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_frozen_m9a_schema(connection):
    metadata = sa.MetaData()
    leads = sa.Table("crm_leads", metadata, sa.Column("id", sa.String(36), primary_key=True))
    contacts = sa.Table(
        "crm_contact_points", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(leads.c.id), nullable=False),
    )
    intents = sa.Table(
        "outreach_intents", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(leads.c.id), nullable=False),
        sa.Column("contact_point_id", sa.String(36), sa.ForeignKey(contacts.c.id), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
    )
    sa.Table(
        "outreach_messages", metadata, sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("outreach_intent_id", sa.String(36), sa.ForeignKey(intents.c.id), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
    )
    metadata.create_all(connection)


def test_m9b_is_one_head_successor_compatible_and_directly_after_m9a():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert REVISION in {
        revision.revision
        for revision in scripts.iterate_revisions(heads[0], "base")
    }
    script = scripts.get_revision(REVISION)
    assert script.down_revision == PREVIOUS
    module = _module()
    assert module.revision == REVISION and module.down_revision == PREVIOUS


def test_m9b_additive_roundtrip_preserves_m9a_and_adds_exactly_two_tables():
    engine = create_engine("sqlite://")
    module = _module()
    try:
        with engine.begin() as connection:
            _create_frozen_m9a_schema(connection)
            before_columns = {
                table: tuple(column["name"] for column in inspect(connection).get_columns(table))
                for table in PRIOR_TABLES
            }
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == PRIOR_TABLES | TABLES
            assert {
                table: tuple(column["name"] for column in inspector.get_columns(table))
                for table in PRIOR_TABLES
            } == before_columns
            attempt_uniques = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("outreach_delivery_attempts")
            }
            event_uniques = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("outreach_delivery_events")
            }
            assert ("source_namespace", "source_event_key") in attempt_uniques
            assert ("outreach_intent_id", "attempt_number") in attempt_uniques
            assert ("delivery_attempt_id", "sequence_number") in event_uniques
            assert ("source_namespace", "source_event_key") in event_uniques
            module.downgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES
            assert {
                table: tuple(column["name"] for column in inspect(connection).get_columns(table))
                for table in PRIOR_TABLES
            } == before_columns
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES | TABLES
    finally:
        engine.dispose()
