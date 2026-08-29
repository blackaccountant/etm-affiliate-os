"""Durable lineage for a grounded content-repurposing execution."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContentRepurposingRun(Base):
    __tablename__ = "content_repurposing_runs"
    __table_args__ = (
        Index("ix_content_repurposing_runs_source_artifact_id", "source_artifact_id"),
        Index("ix_content_repurposing_runs_source_evaluation_id", "source_evaluation_id"),
        Index("ix_content_repurposing_runs_status", "status"),
        Index("ix_content_repurposing_runs_target_content_type", "target_content_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("generated_content_artifacts.id"), nullable=False)
    source_evaluation_id: Mapped[str] = mapped_column(ForeignKey("content_evaluations.id"), nullable=False)
    generation_run_id: Mapped[str] = mapped_column(ForeignKey("content_generation_runs.id"), nullable=False, unique=True)
    result_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("generated_content_artifacts.id"), nullable=True, unique=True)
    target_content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_intent: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)

    def transition_to(self, new_status: str) -> str:
        allowed = {"CREATED": {"RUNNING"}, "RUNNING": {"COMPLETED", "FAILED"}}
        if new_status not in allowed.get(self.status, set()):
            raise ValueError(f"illegal ContentRepurposingRun transition: {self.status} -> {new_status}")
        now = _now()
        self.status = new_status
        self.updated_at = now
        if new_status == "RUNNING":
            self.started_at = now
        if new_status in {"COMPLETED", "FAILED"}:
            self.completed_at = now
        return self.status
