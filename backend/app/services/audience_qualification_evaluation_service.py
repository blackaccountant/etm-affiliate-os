"""Caller-owned M7C assembly of a complete immutable assessment."""
from app.audience.contextual_qualification import qualify_contextually
from app.audience.contextual_qualification_contracts import ContextualQualificationInput
from app.audience.intent_scoring import score_intent
from app.audience.intent_scoring_contracts import IntentScoringInput
from app.audience.qualification_contracts import (
    QualificationAssessmentInput, QualificationContributionInput, context_fingerprint,
    qualification_ruleset_fingerprint,
)
from app.models.audience import AudienceProfile, AudienceSegmentMembership, AudienceSubject
from app.services.audience_qualification_service import AudienceQualificationService
from app.services.audience_segment_membership_service import AudienceSegmentMembershipService


class AudienceQualificationEvaluationService:
    def __init__(self, db): self.db = db
    def evaluate(self, profile_id, ruleset, context, membership_ids=()):
        # Compute canonical fingerprints before evaluation; M7A persists these exact values.
        qualification_ruleset_fingerprint(ruleset)
        context_fingerprint(context)
        profile = self.db.get(AudienceProfile, profile_id); subject = profile and self.db.get(AudienceSubject, profile.subject_id)
        if profile is None or subject is None: raise ValueError("profile subject not found")
        facts = AudienceSegmentMembershipService(self.db)._facts(profile)
        memberships = tuple(self.db.get(AudienceSegmentMembership, value) for value in membership_ids)
        if any(item is None or item.profile_id != profile.id for item in memberships): raise ValueError("invalid membership provenance")
        scoring = score_intent(IntentScoringInput(tuple(facts), profile.effective_as_of, ruleset))
        contextual = qualify_contextually(ContextualQualificationInput(scoring, tuple(facts), subject.subject_type, context, ruleset, tuple((item.segment_revision_id, item.is_member) for item in memberships)))
        dimensions = {**scoring.dimensions, "business_need_fit": contextual.business_need_fit}
        contributions = tuple(
            QualificationContributionInput(
                item.source_signal_id, item.dimension, item.rule_id, item.strength,
                item.confidence, item.raw_amount, item.confidence_adjusted_amount,
                item.final_amount, item.disposition,
            )
            for item in tuple(scoring.contributions) + tuple(contextual.contributions)
        )
        return AudienceQualificationService(self.db).persist(QualificationAssessmentInput(profile.id, ruleset, context, tuple(membership_ids), dimensions, scoring.intent_score, contextual.qualification_score, contextual.qualification_status, profile.effective_as_of, contributions))
