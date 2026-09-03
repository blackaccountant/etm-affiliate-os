"""Historical Core-only M10A2 migration qualification."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


PREVIOUS_REVISION = "f2e3d4c5b6a7"
M10A2_REVISION = "a3b4c5d6e7f8"
DATABASE = "etm_g5_m10a2_migration_qualification"
RAW_URL = os.getenv("ETM_G5_M10A2_MIGRATION_DATABASE_URL")
if not RAW_URL:
    pytest.skip("requires guarded ETM_G5_M10A2_MIGRATION_DATABASE_URL", allow_module_level=True)
URL = make_url(RAW_URL)
if not (
    URL.drivername.startswith("postgresql")
    and URL.host == "127.0.0.1"
    and URL.port == 5432
    and URL.database == DATABASE
):
    raise RuntimeError("M10A2 historical migration qualification database guard failed")

engine = create_engine(URL.render_as_string(hide_password=False), pool_pre_ping=True)


@pytest.fixture(scope="module", autouse=True)
def guarded_historical_schema():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == DATABASE
        assert MigrationContext.configure(connection).get_current_revision() == PREVIOUS_REVISION
    yield
    engine.dispose()


def _migrate(target_revision):
    configured = make_url(os.environ["DATABASE_URL"])
    assert configured.database == DATABASE
    assert configured.host == "127.0.0.1" and configured.port == 5432
    engine.dispose()
    config = Config("alembic.ini")
    if target_revision == PREVIOUS_REVISION:
        command.downgrade(config, target_revision)
    else:
        command.upgrade(config, target_revision)


def test_populated_f2_upgrade_and_downgrade_preserve_unowned_function():
    token, now = uuid4().hex, datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION reject_attribution_fact_mutation()
            RETURNS integer LANGUAGE sql AS $$ SELECT 42 $$
        """))
        product_id = connection.execute(text("""
            INSERT INTO products
            (name, website, category, affiliate_program, commission_type, commission_value,
             affiliate_score, grade, confidence, summary, recommendation, status, created_at)
            VALUES (:name, :website, 'test', 'yes', 'flat', '10', 1, 'A', 100, '', '', 'active', :now)
            RETURNING id
        """), {"name": f"historical-{token}", "website": f"https://{token}.invalid", "now": now}).scalar_one()
        program_id = connection.execute(text("""
            INSERT INTO affiliate_programs (product_id, program_name, confidence, status, created_at)
            VALUES (:product_id, :name, 0, 'active', :now) RETURNING id
        """), {"product_id": product_id, "name": f"program-{token}", "now": now}).scalar_one()
        asset_id = connection.execute(text("""
            INSERT INTO affiliate_content_assets (product_id, asset_type, title)
            VALUES (:product_id, 'article', 'M10A2') RETURNING id
        """), {"product_id": product_id}).scalar_one()
        queue_id = connection.execute(text("""
            INSERT INTO publishing_queue (content_asset_id, status, channel)
            VALUES (:asset_id, 'queued', :channel) RETURNING id
        """), {"asset_id": asset_id, "channel": f"m10a2-{token}"}).scalar_one()
        link_id = connection.execute(text("""
            INSERT INTO affiliate_links
            (affiliate_program_id, content_asset_id, name, destination_url, tracking_code, is_active, created_at)
            VALUES (:program_id, :asset_id, 'M10A2', 'https://destination.invalid', :tracking, true, :now)
            RETURNING id
        """), {"program_id": program_id, "asset_id": asset_id, "tracking": f"m10a2-{token}", "now": now}).scalar_one()
        conversion_id = connection.execute(text("""
            INSERT INTO affiliate_conversions
            (affiliate_link_id, affiliate_program_id, external_conversion_id, sale_amount, currency,
             conversion_status, commission_amount, source, created_at, updated_at)
            VALUES (:link_id, :program_id, :external_id, 0, 'USD', 'pending', 0, 'qualification', :now, :now)
            RETURNING id
        """), {"link_id": link_id, "program_id": program_id, "external_id": f"conversion-{token}", "now": now}).scalar_one()

    _migrate(M10A2_REVISION)
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == M10A2_REVISION
        assert connection.execute(text("SELECT name FROM products WHERE id=:id"), {"id": product_id}).scalar_one() == f"historical-{token}"
        assert connection.execute(text("SELECT product_id FROM affiliate_programs WHERE id=:id"), {"id": program_id}).scalar_one() == product_id
        assert connection.execute(text("SELECT content_asset_id FROM publishing_queue WHERE id=:id"), {"id": queue_id}).scalar_one() == asset_id
        assert connection.execute(text("SELECT affiliate_program_id FROM affiliate_links WHERE id=:id"), {"id": link_id}).scalar_one() == program_id
        assert connection.execute(text("SELECT affiliate_program_id FROM affiliate_conversions WHERE id=:id"), {"id": conversion_id}).scalar_one() == program_id
        assert {row[0] for row in connection.execute(text("""
            SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'attribution_%'
        """))} == {"attribution_publications", "attribution_contexts", "attribution_clicks", "attribution_facts"}

    _migrate(PREVIOUS_REVISION)
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == PREVIOUS_REVISION
        assert connection.execute(text("SELECT reject_attribution_fact_mutation()")).scalar_one() == 42
        assert connection.execute(text("SELECT count(*) FROM pg_proc WHERE proname='m10a2_reject_attribution_fact_mutation'" )).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='trg_attribution_facts_append_only' AND NOT tgisinternal")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM products WHERE id=:id"), {"id": product_id}).scalar_one() == 1

    _migrate(M10A2_REVISION)
    with engine.begin() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == M10A2_REVISION
        assert connection.execute(text("SELECT reject_attribution_fact_mutation()")).scalar_one() == 42
        assert connection.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname='trg_attribution_facts_append_only' AND NOT tgisinternal")).scalar_one() == 1
        connection.execute(text("DROP FUNCTION reject_attribution_fact_mutation()"))
