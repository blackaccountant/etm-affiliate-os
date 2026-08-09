"""
Pytest database fixtures for ETM Affiliate OS.
"""

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models.product import Product


@pytest.fixture
def db_session():
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

    # Register the Product model with Base.metadata.
    Product

    Base.metadata.create_all(
        bind=engine
    )

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    session = TestingSessionLocal()

    try:

        yield session

    finally:

        session.close()

        Base.metadata.drop_all(
            bind=engine
        )

        engine.dispose()