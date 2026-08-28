"""Durable persistence model for workforce workers."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, Float, Integer, String

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now():
    return datetime.now(timezone.utc)


class Worker(Base):
    """Durable worker state used by future cross-process orchestration."""

    __tablename__ = "workers"

    name = Column(String, primary_key=True)
    worker_type = Column(String, nullable=False)
    capabilities = Column(JSON, nullable=False, default=list)
    status = Column(String, nullable=False, index=True)
    current_mission_id = Column(String, nullable=True, index=True)
    missions_completed = Column(Integer, nullable=False, default=0)
    missions_failed = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=False, default=100.0)
    created_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime(), nullable=False, default=utc_now)
    last_assigned_at = Column(UTCDateTime(), nullable=True)
    last_released_at = Column(UTCDateTime(), nullable=True)
