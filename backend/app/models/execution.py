"""
Execution Model

Stores workflow execution history,
mission state, and retry information.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    Text,
)

from app.database.base import Base


class Execution(Base):

    __tablename__ = "executions"


    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )


    mission_id = Column(
        String,
        nullable=True,
        index=True,
    )


    mission_name = Column(
        String,
        nullable=True,
    )


    worker_name = Column(
        String,
        nullable=True,
    )


    workflow_name = Column(
        String,
        nullable=False,
    )


    status = Column(
        String,
        nullable=False,
    )


    result_data = Column(
        Text,
        nullable=True,
    )


    started_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


    completed_at = Column(
        DateTime,
        nullable=True,
    )


    duration = Column(
        Float,
        default=0.0,
    )


    retry_count = Column(
        Integer,
        default=0,
    )


    max_retries = Column(
        Integer,
        default=3,
    )


    next_retry_at = Column(
        DateTime,
        nullable=True,
    )


    failure_type = Column(
        String,
        nullable=True,
    )


    error = Column(
        Text,
        nullable=True,
    )