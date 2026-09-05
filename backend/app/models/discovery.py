"""Durable source-agnostic discovery ledger models."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


JsonValue = JSON()


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_discovery_runs_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    input_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    input_value: Mapped[str] = mapped_column(Text, nullable=False)
    input_data: Mapped[object | None] = mapped_column(JsonValue, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    candidates = relationship("DiscoveryCandidate", back_populates="run", cascade="all, delete-orphan")


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_discovery_candidates_run_dedupe"),
        CheckConstraint("commission_percent IS NULL OR (commission_percent >= 0 AND commission_percent <= 100)", name="ck_discovery_candidate_commission_percent"),
        CheckConstraint("cookie_days IS NULL OR cookie_days >= 0", name="ck_discovery_candidate_cookie_days"),
        CheckConstraint("payout_threshold IS NULL OR payout_threshold >= 0", name="ck_discovery_candidate_payout_threshold"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 100)", name="ck_discovery_candidate_confidence"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_discovery_candidate_score"),
        Index("ix_discovery_candidates_program_identity_key", "program_identity_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("discovery_runs.id"), nullable=False, index=True)
    source_adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    offer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affiliate_network: Mapped[str | None] = mapped_column(String(255), nullable=True)
    affiliate_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    program_identity_key: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(100), nullable=False)
    commission_model: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    commission_percent: Mapped[object | None] = mapped_column(Numeric(5, 2), nullable=True)
    commission_amount: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    recurring_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cookie_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payout_threshold: Mapped[object | None] = mapped_column(Numeric(14, 2), nullable=True)
    payout_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    disposition: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_breakdown: Mapped[object | None] = mapped_column(JsonValue, nullable=True)
    score_reasons: Mapped[object | None] = mapped_column(JsonValue, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    run = relationship("DiscoveryRun", back_populates="candidates")
    evidence_observations = relationship("EvidenceObservation", back_populates="candidate", cascade="all, delete-orphan")


class EvidenceObservation(Base):
    __tablename__ = "evidence_observations"
    __table_args__ = (Index("ix_evidence_observations_candidate_claim", "candidate_id", "claim_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("discovery_candidates.id"), nullable=False, index=True)
    claim_type: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_value: Mapped[object] = mapped_column(JsonValue, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extractor: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    candidate = relationship("DiscoveryCandidate", back_populates="evidence_observations")
