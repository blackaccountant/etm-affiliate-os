from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from app.database.base import Base
from app.database.types import UTCDateTime

def _now(): return datetime.now(timezone.utc)

class ContentEvaluation(Base):
    __tablename__ = "content_evaluations"
    __table_args__ = (UniqueConstraint("artifact_id", "evaluator_version", "policy_version", name="uq_content_evaluations_identity"), Index("ix_content_evaluations_artifact_id", "artifact_id"), Index("ix_content_evaluations_decision", "decision"), Index("ix_content_evaluations_evaluator_version", "evaluator_version"), Index("ix_content_evaluations_policy_version", "policy_version"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("generated_content_artifacts.id"), nullable=False)
    content_brief_id: Mapped[str] = mapped_column(ForeignKey("content_briefs.id"), nullable=False)
    generation_run_id: Mapped[str] = mapped_column(ForeignKey("content_generation_runs.id"), nullable=False)
    factual_grounding_score: Mapped[int] = mapped_column(Integer, nullable=False); offer_alignment_score: Mapped[int] = mapped_column(Integer, nullable=False); intent_alignment_score: Mapped[int] = mapped_column(Integer, nullable=False); clarity_score: Mapped[int] = mapped_column(Integer, nullable=False); cta_score: Mapped[int] = mapped_column(Integer, nullable=False); compliance_score: Mapped[int] = mapped_column(Integer, nullable=False); overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False); approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(100), nullable=False); policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_results: Mapped[object] = mapped_column(JSON, nullable=False); compliance_flags: Mapped[object] = mapped_column(JSON, nullable=False); unsupported_claims: Mapped[object] = mapped_column(JSON, nullable=False); missing_evidence_ids: Mapped[object] = mapped_column(JSON, nullable=False); revision_reasons: Mapped[object] = mapped_column(JSON, nullable=False); rejection_reasons: Mapped[object] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now); updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_now)
