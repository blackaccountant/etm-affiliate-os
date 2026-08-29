"""Repository for provenance links between content briefs and evidence observations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.content_brief_evidence import ContentBriefEvidence


class ContentBriefEvidenceRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, *, content_brief_id: str, evidence_observation_id: str, usage_role: str = "PRIMARY") -> ContentBriefEvidence:
        record = ContentBriefEvidence(
            id=str(uuid4()),
            content_brief_id=content_brief_id,
            evidence_observation_id=evidence_observation_id,
            usage_role=usage_role,
            created_at=self._utc_now(),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_by_brief(self, brief_id: str) -> list[ContentBriefEvidence]:
        return self.db.query(ContentBriefEvidence).filter(ContentBriefEvidence.content_brief_id == brief_id).order_by(ContentBriefEvidence.created_at.asc()).all()
