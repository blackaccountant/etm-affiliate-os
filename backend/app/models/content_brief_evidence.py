"""Provenance bridge between a content brief and the trusted evidence observations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ContentBriefEvidence(Base):
    __tablename__ = "content_brief_evidence"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "evidence_observation_id", "usage_role", name="uq_content_brief_evidence_tuple"),
        Index("ix_content_brief_evidence_brief_usage", "content_brief_id", "usage_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_brief_id: Mapped[str] = mapped_column(ForeignKey("content_briefs.id"), nullable=False, index=True)
    evidence_observation_id: Mapped[str] = mapped_column(ForeignKey("evidence_observations.id"), nullable=False, index=True)
    usage_role: Mapped[str] = mapped_column(String(64), nullable=False, default="PRIMARY", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    brief = relationship("ContentBrief", back_populates="evidence")
    evidence_observation = relationship("EvidenceObservation")
