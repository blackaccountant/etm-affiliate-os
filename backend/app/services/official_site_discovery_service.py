"""Persist official-site discovery adapter results into the durable ledger."""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.discovery.adapters.base import AdapterDiscoveryResult
from app.discovery.adapters.official_site import OfficialSiteDiscoveryAdapter
from app.discovery.contracts import EvidenceObservationCreate, VerificationStatus
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository


class OfficialSiteDiscoveryService:
    """Ingest one URL while preserving all distinct field-level observations."""

    def __init__(self, db: Session, adapter: OfficialSiteDiscoveryAdapter | None = None):
        self.db = db
        self.adapter = adapter or OfficialSiteDiscoveryAdapter()
        self.runs = DiscoveryRunRepository(db)
        self.candidates = DiscoveryCandidateRepository(db)
        self.evidence = EvidenceObservationRepository(db)

    def ingest(self, run_id: str, url: str) -> AdapterDiscoveryResult | None:
        if self.runs.get_by_id(run_id) is None:
            raise ValueError("discovery run does not exist")
        result = self.adapter.discover(url)
        if result is None:
            return None
        candidate = self.candidates.upsert_or_return_existing(run_id, result.candidate)
        existing = {
            self._evidence_key(row.claim_type, row.observed_value, row.source_url, row.excerpt, row.content_hash)
            for row in self.evidence.list_by_candidate(candidate.id)
        }
        for item in result.evidence:
            key = self._evidence_key(item.claim_type, item.observed_value, item.source_url, item.excerpt, item.content_hash)
            if key not in existing:
                self.evidence.create(EvidenceObservationCreate(
                    candidate_id=candidate.id, claim_type=item.claim_type, observed_value=item.observed_value,
                    source_url=item.source_url, source_type=self.adapter.source_type, excerpt=item.excerpt,
                    http_status=item.http_status, content_hash=item.content_hash, extractor=self.adapter.extractor,
                    extractor_version=self.adapter.extractor_version, confidence=item.confidence,
                ))
                existing.add(key)
        candidates = self.candidates.list_by_run(run_id)
        self.runs.update_counters(
            run_id,
            candidate_count=len(candidates),
            verified_count=sum(item.verification_status == VerificationStatus.VERIFIED.value for item in candidates),
        )
        return result

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _evidence_key(cls, claim_type, observed_value, source_url, excerpt, content_hash):
        # SQLite returns JSON true as 1, while PostgreSQL preserves a boolean.
        if claim_type == "affiliate_program_exists":
            observed_value = bool(observed_value)
        elif isinstance(observed_value, (int, float, Decimal)) and not isinstance(observed_value, bool):
            observed_value = format(Decimal(str(observed_value)).normalize(), "f")
        return (claim_type, cls._json(observed_value), source_url, excerpt, content_hash)
