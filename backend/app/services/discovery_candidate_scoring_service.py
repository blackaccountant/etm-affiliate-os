"""Typed candidate scoring, ranking, and durable winner selection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.discovery.contracts import CandidateDisposition, CommissionModel, VerificationStatus
from app.intelligence.scoring import AffiliateScoringEngine
from app.models.discovery import DiscoveryCandidate
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.schemas.affiliate_analysis import AffiliateAnalysis


SCORING_VERSION = "discovery_candidate_scoring_v1"


@dataclass(frozen=True)
class RankedDiscoveryCandidate:
    candidate: DiscoveryCandidate
    evidence_count: int


@dataclass(frozen=True)
class DiscoverySelectionResult:
    selected_ids: tuple[str, ...]


class DiscoveryCandidateScoringService:
    """Bridge typed ledger facts into the existing authoritative scoring engine."""

    def __init__(self, db: Session, engine: AffiliateScoringEngine | None = None):
        self.db = db
        self.engine = engine or AffiliateScoringEngine()
        self.candidates = DiscoveryCandidateRepository(db)
        self.evidence = EvidenceObservationRepository(db)

    def score_candidate(self, candidate_id: str) -> DiscoveryCandidate:
        candidate = self.candidates.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError("discovery candidate does not exist")
        observations = sorted(
            self.evidence.list_by_candidate(candidate.id),
            key=lambda item: (item.source_url or "", item.claim_type, item.excerpt or "", item.content_hash or "", item.id),
        )
        discovery = self.to_legacy_discovery(candidate, observations)
        result = self.engine.score(self._commercial_shell(candidate), discovery)
        breakdown = {
            "scoring_version": SCORING_VERSION,
            "basis": "affiliate_economics_only",
            "commercial_enrichment_applied": False,
            "grade": result.grade,
            "engine_confidence": result.confidence,
            "verification_status": candidate.verification_status,
            "commission_model": candidate.commission_model,
            "commission_percent": self._json_decimal(candidate.commission_percent),
            "commission_amount": self._json_decimal(candidate.commission_amount),
            "cookie_days": candidate.cookie_days,
            "affiliate_network": candidate.affiliate_network,
            "evidence_count": len(observations),
        }
        reasons = [reason.model_dump(mode="json") for reason in result.reasons]
        return self.candidates.save_score(candidate.id, result.score, breakdown, reasons)

    @staticmethod
    def _commercial_shell(candidate: DiscoveryCandidate) -> AffiliateAnalysis:
        return AffiliateAnalysis(
            company=candidate.vendor_name or candidate.canonical_domain,
            website=candidate.source_url or f"https://{candidate.canonical_domain}",
            category="",
            summary="",
            target_audience=[],
            pricing_model="",
            affiliate_program_likely="",
            commission_type="",
            commission_estimate="",
            recommendation="",
        )

    @classmethod
    def to_legacy_discovery(cls, candidate: DiscoveryCandidate, observations) -> dict:
        found, likely = cls._verification(candidate.verification_status)
        commission_type, commission_estimate = cls._commission(candidate)
        return {
            "affiliate_program_found": found,
            "affiliate_program_likely": likely,
            "commission_type": commission_type,
            "commission_estimate": commission_estimate,
            "cookie_window": f"{candidate.cookie_days} days" if candidate.cookie_days is not None else "Unknown",
            "affiliate_platform": candidate.affiliate_network or "Unknown",
            "confidence": candidate.confidence if candidate.confidence is not None else 0,
            "evidence": [item.excerpt for item in observations if item.excerpt],
        }

    @staticmethod
    def _verification(status: str) -> tuple[bool, str]:
        if status == VerificationStatus.VERIFIED.value:
            return True, "Yes"
        if status == VerificationStatus.PARTIAL.value:
            return False, "Likely"
        return False, "Unknown"

    @classmethod
    def _commission(cls, candidate: DiscoveryCandidate) -> tuple[str, str]:
        model = CommissionModel(candidate.commission_model)
        percent = cls._json_decimal(candidate.commission_percent)
        amount = cls._json_decimal(candidate.commission_amount)
        currency = f"{candidate.commission_currency} " if candidate.commission_currency else ""
        if model is CommissionModel.RECURRING_PERCENT and percent is not None:
            return "Recurring Percentage", f"{percent}% recurring"
        if model is CommissionModel.PERCENT and percent is not None:
            return "Percentage", f"{percent}%"
        if model in {CommissionModel.FIXED, CommissionModel.CPA, CommissionModel.CPL, CommissionModel.RECURRING_FIXED} and amount is not None:
            return model.value, f"{currency}{amount}".strip()
        return "Unknown", "Unknown"

    @staticmethod
    def _json_decimal(value) -> str | None:
        return format(Decimal(str(value)).normalize(), "f") if value is not None else None


class DiscoveryRankingService:
    """Read-only deterministic ranking over durable candidate facts."""

    _VERIFICATION_ORDER = {
        VerificationStatus.VERIFIED.value: 0,
        VerificationStatus.PARTIAL.value: 1,
        VerificationStatus.UNVERIFIED.value: 2,
        VerificationStatus.STALE.value: 3,
    }
    _COMMISSION_ORDER = {
        CommissionModel.RECURRING_PERCENT.value: 0,
        CommissionModel.RECURRING_FIXED.value: 1,
        CommissionModel.REVENUE_SHARE.value: 2,
        CommissionModel.PERCENT.value: 3,
        CommissionModel.FIXED.value: 4,
        CommissionModel.CPA.value: 5,
        CommissionModel.CPL.value: 6,
        CommissionModel.UNKNOWN.value: 7,
    }

    def __init__(self, db: Session):
        self.candidates = DiscoveryCandidateRepository(db)

    def rank(self, run_id: str) -> list[RankedDiscoveryCandidate]:
        ranked = [RankedDiscoveryCandidate(candidate, count) for candidate, count in self.candidates.list_with_evidence_counts(run_id)]
        return sorted(ranked, key=self._sort_key)

    @classmethod
    def _sort_key(cls, item: RankedDiscoveryCandidate):
        candidate = item.candidate
        return (
            cls._VERIFICATION_ORDER.get(candidate.verification_status, 99),
            -(candidate.score if candidate.score is not None else -1),
            -(candidate.confidence if candidate.confidence is not None else -1),
            cls._COMMISSION_ORDER.get(candidate.commission_model, 99),
            -cls._numeric(candidate.commission_percent),
            -cls._numeric(candidate.commission_amount),
            -(candidate.cookie_days if candidate.cookie_days is not None else -1),
            -item.evidence_count,
            candidate.program_identity_key,
            candidate.id,
        )

    @staticmethod
    def _numeric(value) -> Decimal:
        return Decimal(str(value)) if value is not None else Decimal("-1")


class DiscoveryWinnerSelectionService:
    """Select deterministic eligible winners without promoting downstream records."""

    def __init__(self, db: Session, ranking: DiscoveryRankingService | None = None):
        self.ranking = ranking or DiscoveryRankingService(db)
        self.candidates = DiscoveryCandidateRepository(db)

    def apply_selection(
        self,
        run_id: str,
        top_n: int = 1,
        minimum_score: int = 40,
        minimum_evidence_confidence: int = 70,
    ) -> DiscoverySelectionResult:
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        selected = []
        for item in self.ranking.rank(run_id):
            candidate = item.candidate
            if self._qualifies(candidate, minimum_score, minimum_evidence_confidence):
                selected.append(candidate.id)
            if len(selected) == top_n:
                break
        self.candidates.apply_selection(run_id, set(selected))
        return DiscoverySelectionResult(tuple(selected))

    @staticmethod
    def _qualifies(candidate: DiscoveryCandidate, minimum_score: int, minimum_confidence: int) -> bool:
        return (
            candidate.disposition != CandidateDisposition.REJECTED.value
            and candidate.verification_status == VerificationStatus.VERIFIED.value
            and candidate.score is not None and candidate.score >= minimum_score
            and candidate.confidence is not None and candidate.confidence >= minimum_confidence
        )
