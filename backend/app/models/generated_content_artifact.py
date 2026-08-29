"""Neutral, grounded output produced from a content-generation run."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def _now():
    return datetime.now(timezone.utc)


class GeneratedContentArtifact(Base):
    __tablename__ = "generated_content_artifacts"
    __table_args__ = (Index("ix_generated_content_artifacts_brief_status", "content_brief_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    generation_run_id: Mapped[str] = mapped_column(ForeignKey("content_generation_runs.id"), nullable=False, unique=True, index=True)
    content_brief_id: Mapped[str] = mapped_column(ForeignKey("content_briefs.id"), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    hook: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    call_to_action: Mapped[str] = mapped_column(Text, nullable=False)
    affiliate_disclosure: Mapped[str] = mapped_column(Text, nullable=False)
    claims: Mapped[object] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="GENERATED", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
