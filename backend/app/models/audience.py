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


class AudienceSignal(Base):
    __tablename__ = "audience_signals"
    __table_args__ = (
        UniqueConstraint("extraction_key", name="uq_audience_signals_extraction_key"),
        CheckConstraint("signal_type IN ('PROBLEM', 'INTEREST', 'INTENT', 'PURCHASE', 'ENGAGEMENT', 'BUSINESS_NEED')", name="ck_audience_signals_type"),
        CheckConstraint("intent_stage IS NULL OR (signal_type = 'INTENT' AND intent_stage IN ('RESEARCH', 'COMPARE', 'EVALUATE', 'PRICING', 'PURCHASE_REQUEST'))", name="ck_audience_signals_intent_stage"),
        CheckConstraint("strength >= 0 AND strength <= 100", name="ck_audience_signals_strength"),
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_audience_signals_confidence"),
        CheckConstraint("length(trim(topic_slug)) > 0", name="ck_audience_signals_topic_slug"),
        CheckConstraint("length(trim(topic_label)) > 0", name="ck_audience_signals_topic_label"),
        CheckConstraint("length(trim(ruleset_version)) > 0", name="ck_audience_signals_ruleset"),
        CheckConstraint("supersedes_signal_id IS NULL OR supersedes_signal_id <> id", name="ck_audience_signals_no_self_supersede"),
        Index("ix_audience_signals_subject_id", "subject_id"), Index("ix_audience_signals_type", "signal_type"),
        Index("ix_audience_signals_topic_slug", "topic_slug"), Index("ix_audience_signals_observed_at", "observed_at"),
        Index("ix_audience_signals_derived_at", "derived_at"), Index("ix_audience_signals_ruleset_version", "ruleset_version"),
        Index("ix_audience_signals_supersedes_signal_id", "supersedes_signal_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("audience_subjects.id"), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    topic_label: Mapped[str] = mapped_column(String(256), nullable=False)
    intent_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strength: Mapped[int] = mapped_column(nullable=False)
    confidence: Mapped[int] = mapped_column(nullable=False)
    evidence_set_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    derived_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    supersedes_signal_id: Mapped[str | None] = mapped_column(ForeignKey("audience_signals.id"), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    subject = relationship("AudienceSubject")
    supersedes_signal = relationship("AudienceSignal", remote_side="AudienceSignal.id")
    evidence_links = relationship("AudienceSignalEvidence", back_populates="signal")


class AudienceSignalEvidence(Base):
    __tablename__ = "audience_signal_evidence"
    __table_args__ = (UniqueConstraint("signal_id", "evidence_id", name="uq_audience_signal_evidence_pair"), Index("ix_audience_signal_evidence_evidence_id", "evidence_id"))
    signal_id: Mapped[str] = mapped_column(ForeignKey("audience_signals.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("audience_evidence.id"), primary_key=True)
    signal = relationship("AudienceSignal", back_populates="evidence_links")
    evidence = relationship("AudienceEvidence")


class AudienceProfile(Base):
    __tablename__ = "audience_profiles"
    __table_args__ = (
        UniqueConstraint("subject_id", "profile_ruleset_version", "source_fingerprint", name="uq_audience_profiles_identity"),
        CheckConstraint("length(trim(profile_ruleset_version)) > 0", name="ck_audience_profiles_ruleset"),
        CheckConstraint("length(trim(source_fingerprint)) = 64", name="ck_audience_profiles_fingerprint"),
        Index("ix_audience_profiles_subject_derived", "subject_id", "derived_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subject_id: Mapped[str] = mapped_column(ForeignKey("audience_subjects.id"), nullable=False)
    profile_ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    derived_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    effective_as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_signal_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    summary_json: Mapped[object] = mapped_column(JSON, nullable=False)
    subject = relationship("AudienceSubject")
    source_signals = relationship("AudienceProfileSignal", back_populates="profile")


class AudienceProfileSignal(Base):
    __tablename__ = "audience_profile_signals"
    __table_args__ = (Index("ix_audience_profile_signals_signal_id", "signal_id"),)
    profile_id: Mapped[str] = mapped_column(ForeignKey("audience_profiles.id"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("audience_signals.id"), primary_key=True)
    profile = relationship("AudienceProfile", back_populates="source_signals")
    signal = relationship("AudienceSignal")


class AudienceSegment(Base):
    __tablename__ = "audience_segments"
    __table_args__ = (
        UniqueConstraint("segment_key", name="uq_audience_segments_key"),
        CheckConstraint("length(trim(segment_key)) > 0", name="ck_audience_segments_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    segment_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revisions = relationship("AudienceSegmentRevision", back_populates="segment")


class AudienceSegmentRevision(Base):
    __tablename__ = "audience_segment_revisions"
    __table_args__ = (
        UniqueConstraint("segment_id", "revision_number", name="uq_audience_segment_revisions_number"),
        UniqueConstraint("segment_id", "segment_ruleset_version", "definition_fingerprint", name="uq_audience_segment_revisions_identity"),
        CheckConstraint("revision_number > 0", name="ck_audience_segment_revisions_number"),
        CheckConstraint("length(trim(segment_ruleset_version)) > 0", name="ck_audience_segment_revisions_ruleset"),
        CheckConstraint("length(trim(definition_fingerprint)) = 64", name="ck_audience_segment_revisions_fingerprint"),
        Index("ix_audience_segment_revisions_segment_number", "segment_id", "revision_number"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(ForeignKey("audience_segments.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False)
    segment_ruleset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_json: Mapped[object] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    segment = relationship("AudienceSegment", back_populates="revisions")


class AudienceSegmentMembership(Base):
    __tablename__ = "audience_segment_memberships"
    __table_args__ = (
        UniqueConstraint("segment_revision_id", "profile_id", name="uq_audience_segment_memberships_identity"),
        Index("ix_audience_segment_memberships_profile_id", "profile_id"),
        Index("ix_audience_segment_memberships_revision_id", "segment_revision_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    segment_revision_id: Mapped[str] = mapped_column(ForeignKey("audience_segment_revisions.id"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey("audience_profiles.id"), nullable=False)
    is_member: Mapped[bool] = mapped_column(nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    segment_revision = relationship("AudienceSegmentRevision")
    profile = relationship("AudienceProfile")
