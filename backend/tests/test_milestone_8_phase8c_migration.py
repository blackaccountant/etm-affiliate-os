"""Structural and isolated roundtrip proof for the additive M8C migration."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


REVISION = "f0a1b2c3d4e5"
PREVIOUS = "e9f0a1b2c3d4"
M8C_TABLES = {"crm_lead_qualification_links", "crm_lead_lifecycle_events"}
PRIOR_TABLES = {"crm_leads", "audience_qualification_assessments"}


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_crm_qualification_lifecycle.py"
    spec = importlib.util.spec_from_file_location("m8c_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_prior_schema(connection):
    metadata = sa.MetaData()
    sa.Table("crm_leads", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "audience_qualification_assessments",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    metadata.create_all(connection)


def test_m8c_revision_is_single_head_and_links_to_frozen_m8a():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    script = scripts.get_revision(REVISION)
    assert scripts.get_current_head() == REVISION
    assert script.down_revision == PREVIOUS
    module = _migration_module()
    assert module.revision == REVISION and module.down_revision == PREVIOUS


def test_m8c_migration_additive_upgrade_downgrade_upgrade_preserves_prior_schema():
    engine = create_engine("sqlite://")
    module = _migration_module()
    try:
        with engine.begin() as connection:
            _create_prior_schema(connection)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES | M8C_TABLES

            link_uniques = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints("crm_lead_qualification_links")
            }
            lifecycle_uniques = {
                tuple(item["column_names"])
                for item in inspect(connection).get_unique_constraints("crm_lead_lifecycle_events")
            }
            assert ("lead_id", "assessment_id") in link_uniques
            assert ("lead_id", "sequence_number") in lifecycle_uniques
            assert ("source_namespace", "source_event_key") in lifecycle_uniques
            checks = {
                item["name"]
                for item in inspect(connection).get_check_constraints("crm_lead_lifecycle_events")
            }
            assert {
                "ck_crm_lead_lifecycle_events_from_state",
                "ck_crm_lead_lifecycle_events_to_state",
                "ck_crm_lead_lifecycle_events_initialization",
                "ck_crm_lead_lifecycle_events_fingerprint",
            } <= checks

            module.downgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES
            assert set(inspect(connection).get_columns("crm_leads")[0]) >= {"name", "type"}
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == PRIOR_TABLES | M8C_TABLES
    finally:
        engine.dispose()
