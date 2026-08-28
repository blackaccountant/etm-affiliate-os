"""
Pytest database fixtures for ETM Affiliate OS.
"""

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app import models  # noqa: F401 - registers all persistence models.


@pytest.fixture
def db_session_factory():
    """
    Provide an isolated in-memory SQLite database
    for each test.
    """

    engine = create_engine(
        "sqlite://",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        bind=engine
    )

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    try:
        yield TestingSessionLocal

    finally:
        Base.metadata.drop_all(
            bind=engine
        )

        engine.dispose()


@pytest.fixture
def db_session(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def isolated_system_mission_manager(db_session_factory, monkeypatch):
    """Bind the preconstructed route manager to SQLite for command tests."""
    from app.system import routes

    class DeterministicEngine:
        def run(self, workflow_name, payload):
            return {
                "success": True,
                "workflow": workflow_name,
                "data": {
                    "products": [{"name": "Test Product", "opportunity_score": 9.0}],
                },
                "errors": [],
            }

    def fail_if_default_session_used():
        raise AssertionError("Remote/default SessionLocal used during isolated test")

    manager = routes.mission_manager
    monkeypatch.setattr(manager, "session_factory", db_session_factory)
    monkeypatch.setattr("app.mission.manager.SessionLocal", fail_if_default_session_used)
    monkeypatch.setattr(manager.executor, "engine", DeterministicEngine())
    manager.clear()
    routes.runtime.memory.clear()
    yield manager
    manager.clear()
    routes.runtime.memory.clear()
