"""Normalized upstream content brief ledger for durable content intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class ContentBrief(Base):
    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_content_briefs_idempotency_key"),
        Index("ix_content_briefs_candidate_run", "discovery_run_id", "discovery_candidate_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    discovery_run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False, index=True)
    discovery_candidate_id: Mapped[str] = mapped_column(ForeignKey("discovery_candidates.id"), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_intent: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    audience_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_to_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_disclosure: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_benefits: Mapped[object | None] = mapped_column(JSON, nullable=True)
    proof_points: Mapped[object | None] = mapped_column(JSON, nullable=True)
    target_keywords: Mapped[object | None] = mapped_column(JSON, nullable=True)
    constraints: Mapped[object | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    discovery_run = relationship("DiscoveryRun")
    discovery_candidate = relationship("DiscoveryCandidate")
    evidence = relationship("ContentBriefEvidence", back_populates="brief", cascade="all, delete-orphan")
    generation_runs = relationship("ContentGenerationRun", back_populates="brief", cascade="all, delete-orphan")

    def transition_to(self, new_status: str) -> str:
        allowed = {
            "CREATED": {"READY"},
            "READY": {"GENERATING", "REJECTED"},
            "GENERATING": {"COMPLETED", "FAILED"},
        }
        if new_status not in allowed.get(self.status, set()):
            raise ValueError(f"illegal ContentBrief transition: {self.status} -> {new_status}")
        self.status = new_status
        self.updated_at = utc_now()
        return self.status
