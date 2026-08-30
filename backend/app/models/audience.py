"""Additive durable models for Audience Intelligence M6.1."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class AudienceResearchRun(Base):
    __tablename__ = "audience_research_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_audience_research_runs_idempotency_key"),
        Index("ix_audience_research_runs_scope_type", "scope_type"),
        Index("ix_audience_research_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_reference: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    metadata_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    observations = relationship("AudienceObservation", back_populates="research_run")


class AudienceSubject(Base):
    __tablename__ = "audience_subjects"
    __table_args__ = (
        CheckConstraint("subject_type IN ('PERSON', 'ORGANIZATION', 'ANONYMOUS')", name="ck_audience_subjects_type"),
        Index("ix_audience_subjects_subject_type", "subject_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    external_identities = relationship("AudienceExternalIdentity", back_populates="subject")
    observations = relationship("AudienceObservation", back_populates="subject")


class AudienceExternalIdentity(Base):
    __tablename__ = "audience_external_identities"
    __table_args__ = (
        UniqueConstraint("source_namespace", "identity_type", "normalized_reference", name="uq_audience_external_identity_reference"),
        CheckConstraint("verification_state IN ('UNVERIFIED', 'VERIFIED', 'FIRST_PARTY_VERIFIED')", name="ck_audience_external_identity_verification"),
        Index("ix_audience_external_identities_subject_id", "subject_id"),
        Index("ix_audience_external_identities_namespace_type", "source_namespace", "identity_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_id: Mapped[str] = mapped_column(ForeignKey("audience_subjects.id"), nullable=False)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    metadata_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    subject = relationship("AudienceSubject", back_populates="external_identities")


class AudienceObservation(Base):
    __tablename__ = "audience_observations"
    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_audience_observations_key"),
        Index("ix_audience_observations_research_run_id", "research_run_id"),
        Index("ix_audience_observations_subject_id", "subject_id"),
        Index("ix_audience_observations_source_namespace_type", "source_namespace", "source_type"),
        Index("ix_audience_observations_observed_at", "observed_at"),
        Index("ix_audience_observations_captured_at", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("audience_research_runs.id"), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("audience_subjects.id"), nullable=True)
    source_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_observation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    observation_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    normalized_fact: Mapped[object] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[object | None] = mapped_column(JSON, nullable=True)

    research_run = relationship("AudienceResearchRun", back_populates="observations")
    subject = relationship("AudienceSubject", back_populates="observations")
    evidence = relationship("AudienceEvidence", back_populates="observation")


class AudienceEvidence(Base):
    __tablename__ = "audience_evidence"
    __table_args__ = (
        UniqueConstraint("observation_id", "evidence_fingerprint", name="uq_audience_evidence_observation_fingerprint"),
        Index("ix_audience_evidence_observation_id", "observation_id"),
        Index("ix_audience_evidence_captured_at", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    observation_id: Mapped[str] = mapped_column(ForeignKey("audience_observations.id"), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_representation: Mapped[object] = mapped_column(JSON, nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[object | None] = mapped_column(JSON, nullable=True)

    observation = relationship("AudienceObservation", back_populates="evidence")
