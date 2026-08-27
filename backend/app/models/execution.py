"""
Execution Model

Stores workflow execution history,
mission state, retry information,
and the immutable input snapshot
required for durable retry replay.
"""

from datetime import datetime, timezone

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


    # ==================================================
    # Workflow Result
    # ==================================================

    result_data = Column(
        Text,
        nullable=True,
    )


    # ==================================================
    # Durable Input Snapshot
    # ==================================================

    input_data = Column(
        Text,
        nullable=True,
    )


    # ==================================================
    # Timing
    # ==================================================
    #
    # All persisted execution timestamps use
    # timezone-aware UTC.
    # ==================================================

    started_at = Column(
        DateTime(
            timezone=True
        ),
        default=lambda: datetime.now(
            timezone.utc
        ),
    )

    completed_at = Column(
        DateTime(
            timezone=True
        ),
        nullable=True,
    )

    duration = Column(
        Float,
        default=0.0,
    )


    # ==================================================
    # Retry State
    # ==================================================

    retry_count = Column(
        Integer,
        default=0,
    )

    max_retries = Column(
        Integer,
        default=3,
    )

    next_retry_at = Column(
        DateTime(
            timezone=True
        ),
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