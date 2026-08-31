"""Successor-compatible structure and isolated roundtrip proof for M9C1."""

import importlib.util
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect


REVISION = "c0d1e2f3a4b5"
PREVIOUS = "b0c1d2e3f4a5"
TABLES = {"outreach_provider_dispatches", "outreach_provider_references"}
PRIOR = {"outreach_delivery_attempts"}


def module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / f"{REVISION}_add_outreach_provider_dispatch.py"
    spec = importlib.util.spec_from_file_location("m9c1_migration", path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def test_revision_is_single_head_exact_parent_and_successor_compatible():
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parents[1] / "alembic.ini")))
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in scripts.iterate_revisions(heads[0], "base")}
    assert scripts.get_revision(REVISION).down_revision == PREVIOUS
    assert module().revision == REVISION and module().down_revision == PREVIOUS


def test_additive_roundtrip_has_exact_tables_uniqueness_and_no_pii_or_secrets():
    engine = create_engine("sqlite://"); migration = module()
    try:
        with engine.begin() as connection:
            metadata = sa.MetaData()
            sa.Table("outreach_delivery_attempts", metadata, sa.Column("id", sa.String(36), primary_key=True))
            metadata.create_all(connection)
            migration.op = Operations(MigrationContext.configure(connection)); migration.upgrade()
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == PRIOR | TABLES
            dispatch_uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("outreach_provider_dispatches")}
            reference_uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("outreach_provider_references")}
            assert ("delivery_attempt_id",) in dispatch_uniques
            assert ("provider_key", "provider_operation_key") in dispatch_uniques
            assert ("provider_dispatch_id",) in reference_uniques
            assert ("provider_key", "provider_reference") in reference_uniques
            columns = {item["name"] for table in TABLES for item in inspector.get_columns(table)}
            assert not {"recipient", "recipient_email", "normalized_value", "api_key", "secret", "body"}.intersection(columns)
            migration.downgrade(); assert set(inspect(connection).get_table_names()) == PRIOR
            migration.upgrade(); assert set(inspect(connection).get_table_names()) == PRIOR | TABLES
    finally:
        engine.dispose()
