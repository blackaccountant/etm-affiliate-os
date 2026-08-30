"""Caller-owned immutable persistence for segment evaluation results."""

from sqlalchemy.exc import IntegrityError
from app.models.audience import AudienceSegmentMembership


class AudienceSegmentMembershipRepository:
    def __init__(self, db): self.db = db
    def get_by_revision_and_profile(self, revision_id, profile_id):
        return self.db.query(AudienceSegmentMembership).filter_by(segment_revision_id=revision_id, profile_id=profile_id).one_or_none()
    def create_or_reuse(self, membership):
        existing = self.get_by_revision_and_profile(membership.segment_revision_id, membership.profile_id)
        if existing is not None: return self._same_or_conflict(existing, membership)
        try:
            with self.db.begin_nested(): self.db.add(membership); self.db.flush()
            return membership
        except IntegrityError:
            existing = self.get_by_revision_and_profile(membership.segment_revision_id, membership.profile_id)
            if existing is None: raise
            return self._same_or_conflict(existing, membership)
    @staticmethod
    def _same_or_conflict(existing, proposed):
        if existing.is_member != proposed.is_member: raise ValueError("segment membership identity conflicts with immutable result")
        return existing
