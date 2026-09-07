"""Append-only persisted snapshots of M11A14 experiment observations."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import UTCDateTime


class EconomicRecommendationExperimentObservation(Base):
    __tablename__ = "economic_recommendation_experiment_observations"
    __table_args__ = (
        UniqueConstraint("observation_fingerprint", name="uq_economic_experiment_observations_fingerprint"),
        Index("ix_economic_experiment_observations_experiment", "experiment_reference"),
        Index("ix_economic_experiment_observations_distribution_run", "distribution_run_id"),
        Index("ix_economic_experiment_observations_execution", "execution_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    activation_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    distribution_run_id: Mapped[str] = mapped_column(ForeignKey("distribution_runs.id"), nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    authorized_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), nullable=False)
    execution_id: Mapped[int] = mapped_column(ForeignKey("executions.id"), nullable=False)
    mission_status: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    distribution_run_status: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    account_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(500), nullable=False)
    result_metadata: Mapped[object | None] = mapped_column(JSON, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    distribution_run_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    execution_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    mission_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    terminal_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    success_failure_classification: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_observation_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_observation_contract_version: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_observation_semantics: Mapped[str] = mapped_column(Text, nullable=False)
    observation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=lambda: datetime.now(timezone.utc))
