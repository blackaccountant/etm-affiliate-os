"""Local structural and isolated roundtrip proof for the additive M8A migration."""

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


REVISION = "e9f0a1b2c3d4"
PREVIOUS = "d8e9f0a1b2c3"
TABLES = {
    "crm_leads",
    "crm_contact_points",
    "crm_contact_point_provenance",
    "crm_contact_point_state_events",
    "crm_permission_events",
    "crm_suppression_events",
}


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_crm_contact_permission_foundation.py"
    spec = importlib.util.spec_from_file_location("m8a_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m8a_revision_is_the_single_head_and_links_to_frozen_m7():
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    script = scripts.get_revision(REVISION)
    assert scripts.get_current_head() == REVISION
    assert script.down_revision == PREVIOUS
    module = _migration_module()
    assert module.revision == REVISION and module.down_revision == PREVIOUS


def test_m8a_migration_isolated_upgrade_downgrade_adds_only_its_tables():
    engine = create_engine("sqlite://")
    module = _migration_module()
    try:
        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            assert set(inspect(connection).get_table_names()) == TABLES
            contact_uniques = {tuple(item["column_names"]) for item in inspect(connection).get_unique_constraints("crm_contact_points")}
            assert ("kind", "normalized_value") in contact_uniques
            suppression_checks = {item["name"] for item in inspect(connection).get_check_constraints("crm_suppression_events")}
            assert "ck_crm_suppression_events_scope_fields" in suppression_checks
            module.downgrade()
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
