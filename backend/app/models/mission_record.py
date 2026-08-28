"""Durable persistence model for the mission aggregate."""

from datetime import datetime, timezone

from sqlalchemy import Column, String, Text

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now():
    return datetime.now(timezone.utc)


class MissionRecord(Base):
    """Long-lived mission state, separate from the in-memory domain object."""

    __tablename__ = "missions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    objective = Column(Text, nullable=False)
    workflow_name = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    input_data = Column(Text, nullable=True)
    required_capability = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, unique=True)
    current_worker_name = Column(String, nullable=True, index=True)
    result_data = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at = Column(UTCDateTime(), nullable=True)
