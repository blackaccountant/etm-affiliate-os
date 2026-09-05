from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def create_database_engine(runtime_settings):
    """Build the synchronous runtime engine without opening a connection."""
    return create_engine(
        runtime_settings.DATABASE_URL,
        echo=runtime_settings.DATABASE_ECHO,
        pool_pre_ping=True,
        pool_recycle=runtime_settings.DATABASE_POOL_RECYCLE_SECONDS,
    )


engine = create_database_engine(settings)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
