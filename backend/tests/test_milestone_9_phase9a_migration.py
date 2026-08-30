"""Structural and isolated roundtrip proof for the additive M9A migration."""

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect


REVISION = "a0b1c2d3e4f5"
PREVIOUS = "f0a1b2c3d4e5"
TABLES = {"outreach_intents", "outreach_messages"}
PRIOR_TABLES = {"crm_leads", "crm_contact_points", "crm_permission_events"}


def _module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_outreach_intent_message.py"
    spec = importlib.util.spec_from_file_location("m9a_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_frozen_m8_schema(connection):
    metadata = sa.MetaData()
    sa.Table("crm_leads", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "crm_contact_points", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["crm_leads.id"]),
    )
    sa.Table(
        "crm_permission_events", metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contact_point_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["contact_point_id"], ["crm_contact_points.id"]),
    )
    metadata.create_all(connection)


def test_m9a_is_single_head_directly_after_frozen_m8():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [REVISION]
    script = scripts.get_revision(REVISION)
    assert script.down_revision == PREVIOUS
    module = _module()
    assert module.revision == REVISION and module.down_revision == PREVIOUS


def test_m9a_isolated_upgrade_downgrade_and_reupgrade_adds_only_two_tables():
    engine = create_engine("sqlite://")
    module = _module()
    try:
        with engine.begin() as connection:
            _create_frozen_m8_schema(connection)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES | TABLES
            intent_uniques = {tuple(item["column_names"]) for item in inspect(connection).get_unique_constraints("outreach_intents")}
            message_uniques = {tuple(item["column_names"]) for item in inspect(connection).get_unique_constraints("outreach_messages")}
            assert ("source_namespace", "source_event_key") in intent_uniques
            assert ("outreach_intent_id",) in message_uniques
            assert {item["name"] for item in inspect(connection).get_check_constraints("outreach_intents")} >= {
                "ck_outreach_intents_channel", "ck_outreach_intents_creation_contactable",
                "ck_outreach_intents_request_fingerprint", "ck_outreach_intents_decision_fingerprint",
            }
            module.downgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES | TABLES
    finally:
        engine.dispose()
