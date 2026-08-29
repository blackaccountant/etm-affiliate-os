"""Durable generation attempts for content briefs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ContentGenerationRun(Base):
    __tablename__ = "content_generation_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_content_generation_runs_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_brief_id: Mapped[str] = mapped_column(ForeignKey("content_briefs.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    generation_parameters: Mapped[object | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    brief = relationship("ContentBrief", back_populates="generation_runs")

    def transition_to(self, new_status: str) -> str:
        allowed = {
            "CREATED": {"RUNNING"},
            "RUNNING": {"RETRY_WAIT", "COMPLETED", "FAILED"},
            "RETRY_WAIT": {"RUNNING"},
        }
        if new_status not in allowed.get(self.status, set()):
            raise ValueError(f"illegal ContentGenerationRun transition: {self.status} -> {new_status}")
        self.status = new_status
        self.updated_at = utc_now()
        if new_status in {"COMPLETED", "FAILED"}:
            self.completed_at = self.updated_at
        return self.status
