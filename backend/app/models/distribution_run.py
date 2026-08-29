"""Durable, idempotent intent to distribute one approved content artifact."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DistributionRun(Base):
    __tablename__ = "distribution_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_distribution_runs_idempotency_key"),
        Index("ix_distribution_runs_generated_content_artifact_id", "generated_content_artifact_id"),
        Index("ix_distribution_runs_content_evaluation_id", "content_evaluation_id"),
        Index("ix_distribution_runs_status", "status"),
        Index("ix_distribution_runs_scheduled_for", "scheduled_for"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    generated_content_artifact_id: Mapped[str] = mapped_column(ForeignKey("generated_content_artifacts.id"), nullable=False)
    content_evaluation_id: Mapped[str] = mapped_column(ForeignKey("content_evaluations.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    account_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    prepared_content_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    external_post_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_metadata: Mapped[object | None] = mapped_column(JSON, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    publishing_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
