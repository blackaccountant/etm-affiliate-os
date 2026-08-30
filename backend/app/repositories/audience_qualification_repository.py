"""Caller-owned immutable persistence for M7 qualification assessments."""

from sqlalchemy.exc import IntegrityError

from app.audience.normalization import canonical_json
from app.models.audience import AudienceQualificationAssessment, AudienceQualificationAssessmentMembership, AudienceQualificationContribution


class AudienceQualificationRepository:
    def __init__(self, db): self.db = db

    def get_by_identity(self, profile_id, ruleset_version, ruleset_fingerprint, context_fingerprint, membership_fingerprint):
        return self.db.query(AudienceQualificationAssessment).filter_by(
            profile_id=profile_id, scoring_ruleset_version=ruleset_version,
            scoring_ruleset_fingerprint=ruleset_fingerprint, context_fingerprint=context_fingerprint,
            selected_membership_fingerprint=membership_fingerprint,
        ).one_or_none()

    def membership_ids(self, assessment_id):
        return [row.membership_id for row in self.db.query(AudienceQualificationAssessmentMembership).filter_by(assessment_id=assessment_id).order_by(AudienceQualificationAssessmentMembership.membership_id)]

    def contributions(self, assessment_id):
        return self.db.query(AudienceQualificationContribution).filter_by(assessment_id=assessment_id).order_by(AudienceQualificationContribution.source_signal_id, AudienceQualificationContribution.dimension, AudienceQualificationContribution.rule_id).all()

    def create_or_reuse(self, assessment, membership_ids, contributions):
        existing = self.get_by_identity(assessment.profile_id, assessment.scoring_ruleset_version, assessment.scoring_ruleset_fingerprint, assessment.context_fingerprint, assessment.selected_membership_fingerprint)
        if existing is not None: return self._same_or_conflict(existing, assessment, membership_ids, contributions)
        try:
            with self.db.begin_nested():
                self.db.add(assessment); self.db.flush()
                for membership_id in membership_ids:
                    self.db.add(AudienceQualificationAssessmentMembership(assessment_id=assessment.id, membership_id=membership_id))
                for contribution in contributions:
                    contribution.assessment_id = assessment.id
                    self.db.add(contribution)
                self.db.flush()
            return assessment
        except IntegrityError:
            existing = self.get_by_identity(assessment.profile_id, assessment.scoring_ruleset_version, assessment.scoring_ruleset_fingerprint, assessment.context_fingerprint, assessment.selected_membership_fingerprint)
            if existing is None: raise
            return self._same_or_conflict(existing, assessment, membership_ids, contributions)

    def _same_or_conflict(self, existing, proposed, membership_ids, contributions):
        stored = (self._assessment_dict(existing), self.membership_ids(existing.id), [self._contribution_dict(row) for row in self.contributions(existing.id)])
        incoming = (self._assessment_dict(proposed), list(membership_ids), [self._contribution_dict(row) for row in contributions])
        if canonical_json(stored) != canonical_json(incoming):
            raise ValueError("qualification assessment identity conflicts with immutable contents")
        return existing

    @staticmethod
    def _assessment_dict(value):
        result = {column: getattr(value, column) for column in (
            "profile_id", "scoring_ruleset_version", "scoring_ruleset_fingerprint", "scoring_ruleset_json",
            "context_type", "context_json", "context_fingerprint", "selected_membership_fingerprint",
            "problem_strength", "interest_alignment", "research_intent", "comparison_intent", "evaluation_intent",
            "pricing_intent", "purchase_request_intent", "purchase_signal", "engagement", "business_need_fit",
            "intent_score", "qualification_score", "qualification_status", "derived_at",
        )}
        result["derived_at"] = result["derived_at"].isoformat()
        return result

    @staticmethod
    def _contribution_dict(value):
        return {column: getattr(value, column) for column in (
            "source_signal_id", "dimension", "rule_id", "strength", "confidence", "raw_amount",
            "confidence_adjusted_amount", "final_amount", "disposition",
        )}
