"""M7A validation and immutable persistence only; no scoring computation."""

from dataclasses import dataclass

from app.audience.qualification_contracts import (
    QualificationAssessmentInput, context_fingerprint, qualification_ruleset_fingerprint,
    selected_membership_fingerprint,
)
from app.models.audience import AudienceProfile, AudienceQualificationAssessment, AudienceQualificationContribution, AudienceSegmentMembership, AudienceSignal
from app.repositories.audience_qualification_repository import AudienceQualificationRepository


class AudienceQualificationError(ValueError):
    def __init__(self, category, message):
        super().__init__(message); self.category = category


@dataclass(frozen=True)
class AudienceQualificationPersistenceResult:
    assessment_id: str
    profile_id: str
    reused: bool


class AudienceQualificationService:
    def __init__(self, db): self.db = db; self.assessments = AudienceQualificationRepository(db)

    def persist(self, value: QualificationAssessmentInput) -> AudienceQualificationPersistenceResult:
        if not isinstance(value, QualificationAssessmentInput):
            raise AudienceQualificationError("INVALID_ASSESSMENT", "assessment input must be typed")
        if self.db.get(AudienceProfile, value.profile_id) is None:
            raise AudienceQualificationError("PROFILE_NOT_FOUND", "audience profile does not exist")
        memberships = [self.db.get(AudienceSegmentMembership, membership_id) for membership_id in value.membership_ids]
        if any(item is None for item in memberships) or any(item.profile_id != value.profile_id for item in memberships):
            raise AudienceQualificationError("INVALID_MEMBERSHIP_PROVENANCE", "memberships must belong to the assessment profile")
        if any(self.db.get(AudienceSignal, item.source_signal_id) is None for item in value.contributions):
            raise AudienceQualificationError("SIGNAL_NOT_FOUND", "contribution source signal does not exist")
        ruleset_fingerprint = qualification_ruleset_fingerprint(value.ruleset)
        context_value = value.context.to_dict()
        context_value_fingerprint = context_fingerprint(value.context)
        membership_value_fingerprint = selected_membership_fingerprint(value.membership_ids)
        existing = self.assessments.get_by_identity(value.profile_id, value.ruleset.version, ruleset_fingerprint, context_value_fingerprint, membership_value_fingerprint)
        assessment = AudienceQualificationAssessment(
            profile_id=value.profile_id, scoring_ruleset_version=value.ruleset.version,
            scoring_ruleset_fingerprint=ruleset_fingerprint, scoring_ruleset_json=value.ruleset.to_dict(),
            context_type=value.context.kind, context_json=context_value, context_fingerprint=context_value_fingerprint,
            selected_membership_fingerprint=membership_value_fingerprint, **value.dimensions,
            intent_score=value.intent_score, qualification_score=value.qualification_score,
            qualification_status=value.qualification_status, derived_at=value.derived_at,
        )
        contributions = [AudienceQualificationContribution(
            source_signal_id=item.source_signal_id, dimension=item.dimension, rule_id=item.rule_id,
            strength=item.strength, confidence=item.confidence, raw_amount=item.raw_amount,
            confidence_adjusted_amount=item.confidence_adjusted_amount, final_amount=item.final_amount,
            disposition=item.disposition,
        ) for item in value.contributions]
        try:
            stored = self.assessments.create_or_reuse(assessment, value.membership_ids, contributions)
        except ValueError as exc:
            raise AudienceQualificationError("IMMUTABLE_ASSESSMENT_CONFLICT", str(exc)) from exc
        return AudienceQualificationPersistenceResult(stored.id, stored.profile_id, existing is not None)
