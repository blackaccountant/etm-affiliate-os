"""Run-scoped durable candidate persistence and duplicate resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.discovery.contracts import CandidateDisposition, DiscoveryCandidateCreate, VerificationStatus
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation


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

    def list_with_evidence_counts(self, run_id: str) -> list[tuple[DiscoveryCandidate, int]]:
        """Return candidates with one aggregate evidence count per durable row."""
        return [
            (candidate, int(evidence_count))
            for candidate, evidence_count in (
                self.db.query(DiscoveryCandidate, func.count(EvidenceObservation.id))
                .outerjoin(EvidenceObservation, EvidenceObservation.candidate_id == DiscoveryCandidate.id)
                .filter(DiscoveryCandidate.run_id == run_id)
                .group_by(DiscoveryCandidate.id)
                .all()
            )
        ]

    def get_by_run_and_dedupe_key(self, run_id: str, dedupe_key: str) -> DiscoveryCandidate | None:
        return self.db.query(DiscoveryCandidate).filter(DiscoveryCandidate.run_id == run_id, DiscoveryCandidate.dedupe_key == dedupe_key).first()

    def upsert_or_return_existing(self, run_id: str, payload: DiscoveryCandidateCreate) -> DiscoveryCandidate:
        existing = self.get_by_run_and_dedupe_key(run_id, payload.dedupe_key)
        return existing if existing is not None else self.create(run_id, payload)

    def save_score(self, candidate_id: str, score: int, score_breakdown: dict, score_reasons: list[dict]) -> DiscoveryCandidate:
        candidate = self.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError("discovery candidate does not exist")
        candidate.score = score
        candidate.score_breakdown = score_breakdown
        candidate.score_reasons = score_reasons
        candidate.updated_at = self._utc_now()
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def set_disposition(self, candidate_id: str, disposition: CandidateDisposition) -> DiscoveryCandidate:
        candidate = self.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError("discovery candidate does not exist")
        candidate.disposition = CandidateDisposition(disposition).value
        candidate.updated_at = self._utc_now()
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def apply_selection(self, run_id: str, selected_ids: set[str]) -> list[DiscoveryCandidate]:
        """Atomically apply winner dispositions and recompute all durable run counters."""
        candidates = self.list_by_run(run_id)
        run = self.db.get(DiscoveryRun, run_id)
        if run is None:
            raise ValueError("discovery run does not exist")
        try:
            for candidate in candidates:
                if candidate.id in selected_ids:
                    candidate.disposition = CandidateDisposition.SELECTED.value
                elif candidate.disposition == CandidateDisposition.REJECTED.value:
                    continue
                elif candidate.verification_status == VerificationStatus.VERIFIED.value:
                    candidate.disposition = CandidateDisposition.VERIFIED.value
                else:
                    candidate.disposition = CandidateDisposition.DISCOVERED.value
                candidate.updated_at = self._utc_now()
            run.candidate_count = len(candidates)
            run.verified_count = sum(item.verification_status == VerificationStatus.VERIFIED.value for item in candidates)
            run.selected_count = sum(item.disposition == CandidateDisposition.SELECTED.value for item in candidates)
            run.updated_at = self._utc_now()
            self.db.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.list_by_run(run_id)
