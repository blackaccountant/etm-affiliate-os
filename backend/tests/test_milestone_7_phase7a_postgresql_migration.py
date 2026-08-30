"""Guarded G5 migration roundtrip for additive M7A assessment tables."""
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings


REVISION, PREVIOUS = "d8e9f0a1b2c3", "c7d3e4f5a6b7"
_raw = os.getenv("ETM_G5_DATABASE_URL")
if not _raw:
    pytest.skip("Requires explicit guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
_url = make_url(_raw)
if not (_url.drivername.startswith("postgresql") and _url.host == "127.0.0.1" and _url.port == 5432 and _url.database == "etm_affiliate_os_g5_test"):
    raise RuntimeError("G5 only")


def _revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_m7a_upgrade_downgrade_upgrade_is_additive():
    engine = create_engine(_url.render_as_string(hide_password=False))
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _url.render_as_string(hide_password=False))
    original_url, subject_id = settings.DATABASE_URL, str(uuid4())
    settings.DATABASE_URL = _url.render_as_string(hide_password=False)
    try:
        if _revision(engine) == REVISION:
            command.downgrade(config, PREVIOUS)
            engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False))
        assert _revision(engine) == PREVIOUS
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO audience_subjects (id, subject_type, created_at, updated_at) VALUES (:id, 'ANONYMOUS', now(), now())"), {"id": subject_id})
        command.upgrade(config, REVISION)
        engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False))
        assert _revision(engine) == REVISION
        expected = {"audience_qualification_assessments", "audience_qualification_assessment_memberships", "audience_qualification_contributions"}
        assert expected <= set(inspect(engine).get_table_names())
        command.downgrade(config, PREVIOUS)
        engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False))
        assert _revision(engine) == PREVIOUS
        assert not expected & set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM audience_subjects WHERE id=:id"), {"id": subject_id}).scalar_one() == 1
        command.upgrade(config, REVISION)
        engine.dispose(); engine = create_engine(_url.render_as_string(hide_password=False))
        assert _revision(engine) == REVISION
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM audience_subjects WHERE id=:id"), {"id": subject_id})
        settings.DATABASE_URL = original_url
        engine.dispose()
