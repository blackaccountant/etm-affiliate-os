from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def create_database_engine(runtime_settings):
    """Build the synchronous runtime engine without opening a connection."""
    engine_options = {
        "echo": runtime_settings.DATABASE_ECHO,
        "pool_pre_ping": True,
        "pool_recycle": runtime_settings.DATABASE_POOL_RECYCLE_SECONDS,
    }
    if make_url(runtime_settings.DATABASE_URL).get_backend_name() == "postgresql":
        engine_options["connect_args"] = {
            "connect_timeout": runtime_settings.DATABASE_CONNECTION_TIMEOUT_SECONDS,
        }
        engine_options["pool_timeout"] = runtime_settings.DATABASE_CONNECTION_TIMEOUT_SECONDS
    return create_engine(runtime_settings.DATABASE_URL, **engine_options)


engine = create_database_engine(settings)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def database_is_ready() -> bool:
    """Return whether the configured database accepts a read-only probe."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
