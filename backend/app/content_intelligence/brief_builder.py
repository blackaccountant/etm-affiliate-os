"""Deterministic, evidence-grounded construction of READY content briefs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy.orm import Session

from app.content_intelligence.contracts import ContentBriefStatus, ContentType, EvidenceUsageRole
from app.models.content_brief import ContentBrief
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.services.content_brief_service import ContentBriefService


AFFILIATE_DISCLOSURE_REQUIRED = "AFFILIATE_DISCLOSURE_REQUIRED"

MANDATORY_CONSTRAINTS = frozenset(
    {
        "AFFILIATE_DISCLOSURE_REQUIRED",
        "EVIDENCE_GROUNDED_ONLY",
        "NO_FABRICATED_ECONOMICS",
        "NO_FAKE_DISCOUNTS",
        "NO_FAKE_URGENCY",
        "NO_GUARANTEED_INCOME",
        "NO_UNSUPPORTED_CLAIMS",
    }
)

_SUPPORTED_EVIDENCE_ROLES = {
    "affiliate_program_exists": EvidenceUsageRole.PRIMARY.value,
    "affiliate_network": EvidenceUsageRole.SUPPORTING.value,
    "affiliate_url": EvidenceUsageRole.CTA_SUPPORT.value,
    "commission_model": EvidenceUsageRole.ECONOMICS.value,
    "commission_percent": EvidenceUsageRole.ECONOMICS.value,
    "commission_amount": EvidenceUsageRole.ECONOMICS.value,
    "commission_currency": EvidenceUsageRole.ECONOMICS.value,
    "recurring_period": EvidenceUsageRole.ECONOMICS.value,
    "cookie_days": EvidenceUsageRole.ECONOMICS.value,
}

_ALLOWED_ANGLES = frozenset(
    {
        "VERIFIED_PROGRAM_SUMMARY",
        "BUYER_GUIDE",
        "REVIEW",
        "COMPARISON",
        "ECONOMICS_REFERENCE",
        "OFFER_DETAILS",
    }
)

_ALLOWED_CTAS = frozenset({"VISIT_OFFER", "CHECK_DETAILS", "LEARN_MORE"})


@dataclass(frozen=True)
class ContentBriefBuildRequest:
    discovery_run_id: str
    discovery_candidate_id: str
    content_type: str
    channel_intent: str
    objective: str
    audience_intent: str | None = None
    audience_problem: str | None = None
    tone: str | None = None
    requested_angle: str | None = None
    requested_cta: str | None = None
    target_keywords: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)


class ContentBriefBuilderService:
    """Build a strategy record from selected discovery facts without generation."""

    def __init__(self, db: Session, brief_service: ContentBriefService | None = None):
        self.db = db
        self.briefs = brief_service or ContentBriefService(db)

    def build(self, request: ContentBriefBuildRequest) -> ContentBrief:
        run, candidate = self._eligible_run_and_candidate(request)
        content_type = self._content_type(request.content_type)
        channel_intent = self._required_text(request.channel_intent, "channel_intent")
        objective = self._required_text(request.objective, "objective")
        evidence = self._supported_evidence(candidate.id)
        if not evidence:
            raise ValueError("at least one valid supported evidence observation is required for a READY brief")

        proof_points = [self._proof_point(item) for item in evidence]
        evidence_links = [
            {
                "evidence_observation_id": item.id,
                "usage_role": _SUPPORTED_EVIDENCE_ROLES[item.claim_type],
            }
            for item in evidence
        ]
        has_affiliate_url = any(item.claim_type == "affiliate_url" for item in evidence)
        has_economics = any(link["usage_role"] == EvidenceUsageRole.ECONOMICS.value for link in evidence_links)
        angle = self._angle(content_type, request.requested_angle, has_economics, has_affiliate_url)
        call_to_action = self._cta(request.requested_cta, has_affiliate_url)

        return self.briefs.create_brief(
            discovery_run_id=run.id,
            discovery_candidate_id=candidate.id,
            content_type=content_type,
            channel_intent=channel_intent,
            objective=objective,
            audience_intent=self._optional_text(request.audience_intent),
            audience_problem=self._optional_text(request.audience_problem),
            angle=angle,
            call_to_action=call_to_action,
            tone=self._optional_text(request.tone),
            required_disclosure=AFFILIATE_DISCLOSURE_REQUIRED,
            key_benefits=[],
            proof_points=proof_points,
            target_keywords=self._keywords(candidate, content_type, request.target_keywords),
            constraints=self._constraints(request.constraints),
            evidence_links=evidence_links,
            status=ContentBriefStatus.READY.value,
            # Evidence IDs are durable provenance, not brief strategy identity.
            identity_proof_points=[],
        )

    def _eligible_run_and_candidate(
        self, request: ContentBriefBuildRequest
    ) -> tuple[DiscoveryRun, DiscoveryCandidate]:
        run = self.db.get(DiscoveryRun, request.discovery_run_id)
        if run is None:
            raise ValueError("discovery run not found")
        candidate = self.db.get(DiscoveryCandidate, request.discovery_candidate_id)
        if candidate is None:
            raise ValueError("discovery candidate not found")
        if candidate.run_id != run.id:
            raise ValueError("candidate does not belong to this run")
        if candidate.disposition != "SELECTED":
            raise ValueError("candidate is not selected")
        if candidate.verification_status != "VERIFIED":
            raise ValueError("candidate is not verified")
        return run, candidate

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{name} is required")
        return normalized

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _content_type(value: str) -> str:
        normalized = str(value or "").strip()
        if normalized not in {item.value for item in ContentType}:
            raise ValueError("content_type is invalid")
        return normalized

    def _supported_evidence(self, candidate_id: str) -> list[EvidenceObservation]:
        observations = self.db.query(EvidenceObservation).filter(EvidenceObservation.candidate_id == candidate_id).all()
        return sorted(
            (
                item
                for item in observations
                if item.claim_type in _SUPPORTED_EVIDENCE_ROLES and self._has_provenance(item)
            ),
            key=self._evidence_sort_key,
        )

    @staticmethod
    def _has_provenance(item: EvidenceObservation) -> bool:
        return bool(
            item.source_url
            and item.source_type.strip()
            and item.extractor.strip()
            and item.extractor_version.strip()
            and item.observed_value is not None
        )

    @staticmethod
    def _evidence_sort_key(item: EvidenceObservation) -> tuple[str, str, str, str, str]:
        observed_value = json.dumps(item.observed_value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return (item.claim_type, observed_value, item.source_url or "", item.excerpt or "", item.id)

    @staticmethod
    def _proof_point(item: EvidenceObservation) -> dict:
        return {
            "evidence_observation_id": item.id,
            "usage_role": _SUPPORTED_EVIDENCE_ROLES[item.claim_type],
            "claim_type": item.claim_type,
            "observed_value": item.observed_value,
            "source_url": item.source_url,
            "excerpt": item.excerpt,
            "confidence": item.confidence,
        }

    @staticmethod
    def _angle(content_type: str, requested: str | None, has_economics: bool, has_affiliate_url: bool) -> str:
        requested = str(requested or "").strip()
        if requested:
            if requested not in _ALLOWED_ANGLES:
                raise ValueError("requested_angle is invalid")
            if requested == "ECONOMICS_REFERENCE" and not has_economics:
                raise ValueError("ECONOMICS_REFERENCE requires economics evidence")
            if requested == "OFFER_DETAILS" and not has_affiliate_url:
                raise ValueError("OFFER_DETAILS requires affiliate_url evidence")
            return requested
        return {
            ContentType.PRODUCT_REVIEW.value: "REVIEW",
            ContentType.COMPARISON.value: "COMPARISON",
            ContentType.BUYER_GUIDE.value: "BUYER_GUIDE",
        }.get(content_type, "VERIFIED_PROGRAM_SUMMARY")

    @staticmethod
    def _cta(requested: str | None, has_affiliate_url: bool) -> str:
        requested = str(requested or "").strip()
        if requested and requested not in _ALLOWED_CTAS:
            raise ValueError("requested_cta is invalid")
        if requested == "VISIT_OFFER" and not has_affiliate_url:
            return "CHECK_DETAILS"
        if requested:
            return requested
        return "VISIT_OFFER" if has_affiliate_url else "CHECK_DETAILS"

    @staticmethod
    def _keywords(candidate: DiscoveryCandidate, content_type: str, requested: Iterable[str]) -> list[str]:
        modifier = {
            ContentType.PRODUCT_REVIEW.value: "review",
            ContentType.COMPARISON.value: "comparison",
            ContentType.BUYER_GUIDE.value: "buyer guide",
        }.get(content_type, "affiliate program")
        identities = (
            candidate.vendor_name,
            candidate.program_name,
            candidate.offer_name,
            candidate.canonical_domain,
        )
        values = list(requested) + [f"{value} {modifier}" for value in identities if value and value.strip()]
        return sorted({" ".join(str(value).strip().lower().split()) for value in values if str(value).strip()})

    @staticmethod
    def _constraints(requested: Iterable[str]) -> list[str]:
        editorial = {str(value).strip() for value in requested if str(value).strip()}
        return sorted(MANDATORY_CONSTRAINTS | editorial)
