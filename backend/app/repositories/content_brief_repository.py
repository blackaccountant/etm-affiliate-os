"""Durable repository for upstream content briefs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.content_brief import ContentBrief


class ContentBriefRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, *, discovery_run_id: str, discovery_candidate_id: str, content_type: str, channel_intent: str,
               objective: str, audience_intent: str | None = None, audience_problem: str | None = None,
               angle: str | None = None, call_to_action: str | None = None, tone: str | None = None,
               required_disclosure: str | None = None, key_benefits: object | None = None,
               proof_points: object | None = None, target_keywords: object | None = None,
               constraints: object | None = None, status: str = "CREATED", idempotency_key: str | None = None) -> ContentBrief:
        record = ContentBrief(
            id=str(uuid4()),
            discovery_run_id=discovery_run_id,
            discovery_candidate_id=discovery_candidate_id,
            content_type=content_type,
            channel_intent=channel_intent,
            objective=objective,
            audience_intent=audience_intent,
            audience_problem=audience_problem,
            angle=angle,
            call_to_action=call_to_action,
            tone=tone,
            required_disclosure=required_disclosure,
            key_benefits=key_benefits,
            proof_points=proof_points,
            target_keywords=target_keywords,
            constraints=constraints,
            idempotency_key=idempotency_key or str(uuid4()),
            status=status,
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_by_id(self, brief_id: str) -> ContentBrief | None:
        return self.db.get(ContentBrief, brief_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> ContentBrief | None:
        return self.db.query(ContentBrief).filter(ContentBrief.idempotency_key == idempotency_key).first()

    def list_by_run(self, run_id: str) -> list[ContentBrief]:
        return self.db.query(ContentBrief).filter(ContentBrief.discovery_run_id == run_id).order_by(ContentBrief.created_at.asc()).all()

    def list_recent(self, limit: int = 50) -> list[ContentBrief]:
        """Return newest durable records first; this query performs no writes."""
        return (
            self.db.query(ContentBrief)
            .order_by(
                ContentBrief.created_at.desc(),
                ContentBrief.id.desc(),
            )
            .limit(limit)
            .all()
        )
