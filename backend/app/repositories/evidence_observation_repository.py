"""Field-specific source provenance persistence for discovery candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.discovery.contracts import EvidenceObservationCreate
from app.models.discovery import EvidenceObservation


class EvidenceObservationRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, payload: EvidenceObservationCreate) -> EvidenceObservation:
        now = self._utc_now()
        record = EvidenceObservation(
            id=str(uuid4()), observed_at=now, created_at=now,
            **payload.model_dump(mode="python"),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_by_candidate(self, candidate_id: str) -> list[EvidenceObservation]:
        return self.db.query(EvidenceObservation).filter(EvidenceObservation.candidate_id == candidate_id).order_by(EvidenceObservation.observed_at.asc()).all()

    def list_by_candidate_and_claim(self, candidate_id: str, claim_type: str) -> list[EvidenceObservation]:
        return self.db.query(EvidenceObservation).filter(EvidenceObservation.candidate_id == candidate_id, EvidenceObservation.claim_type == claim_type).order_by(EvidenceObservation.observed_at.asc()).all()
