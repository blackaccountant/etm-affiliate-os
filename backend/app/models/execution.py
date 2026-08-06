"""
Execution Model

Stores workflow execution history.
"""

from datetime import datetime

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import Float

from app.database.base import Base


class Execution(Base):

    __tablename__ = "executions"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    workflow_name = Column(
        String,
        nullable=False,
    )

    status = Column(
        String,
        nullable=False,
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

    error = Column(
        String,
        nullable=True,
    )