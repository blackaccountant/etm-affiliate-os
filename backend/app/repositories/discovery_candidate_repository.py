"""Run-scoped durable candidate persistence and duplicate resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.discovery.contracts import DiscoveryCandidateCreate
from app.models.discovery import DiscoveryCandidate


class DiscoveryCandidateRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, run_id: str, payload: DiscoveryCandidateCreate) -> DiscoveryCandidate:
        now = self._utc_now()
        candidate = DiscoveryCandidate(
            id=str(uuid4()), run_id=run_id, created_at=now, updated_at=now,
            **payload.model_dump(mode="python"),
        )
        self.db.add(candidate)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.get_by_run_and_dedupe_key(run_id, payload.dedupe_key)
            if existing is None:
                raise
            return existing
        self.db.refresh(candidate)
        return candidate

    def get_by_id(self, candidate_id: str) -> DiscoveryCandidate | None:
        return self.db.get(DiscoveryCandidate, candidate_id)

    def list_by_run(self, run_id: str) -> list[DiscoveryCandidate]:
        return self.db.query(DiscoveryCandidate).filter(DiscoveryCandidate.run_id == run_id).order_by(DiscoveryCandidate.created_at.asc()).all()

    def get_by_run_and_dedupe_key(self, run_id: str, dedupe_key: str) -> DiscoveryCandidate | None:
        return self.db.query(DiscoveryCandidate).filter(DiscoveryCandidate.run_id == run_id, DiscoveryCandidate.dedupe_key == dedupe_key).first()

    def upsert_or_return_existing(self, run_id: str, payload: DiscoveryCandidateCreate) -> DiscoveryCandidate:
        existing = self.get_by_run_and_dedupe_key(run_id, payload.dedupe_key)
        return existing if existing is not None else self.create(run_id, payload)
