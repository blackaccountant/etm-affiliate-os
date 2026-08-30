"""Caller-owned immutable persistence for audience profile snapshots."""

from sqlalchemy.exc import IntegrityError

from app.audience.normalization import canonical_json
from app.models.audience import AudienceProfile, AudienceProfileSignal


class AudienceProfileRepository:
    def __init__(self, db): self.db = db
    def get_by_id(self, profile_id): return self.db.get(AudienceProfile, profile_id)
    def get_by_identity(self, subject_id, profile_ruleset_version, source_fingerprint):
        return self.db.query(AudienceProfile).filter_by(subject_id=subject_id, profile_ruleset_version=profile_ruleset_version, source_fingerprint=source_fingerprint).one_or_none()
    def list_signal_ids(self, profile_id):
        return [row.signal_id for row in self.db.query(AudienceProfileSignal).filter_by(profile_id=profile_id).order_by(AudienceProfileSignal.signal_id)]
    def create_or_reuse(self, profile, signal_ids):
        existing = self.get_by_identity(profile.subject_id, profile.profile_ruleset_version, profile.source_fingerprint)
        if existing is not None: return self._same_or_conflict(existing, profile, signal_ids)
        try:
            with self.db.begin_nested():
                self.db.add(profile); self.db.flush()
                for signal_id in sorted(set(signal_ids)): self.db.add(AudienceProfileSignal(profile_id=profile.id, signal_id=signal_id))
                self.db.flush()
            return profile
        except IntegrityError:
            existing = self.get_by_identity(profile.subject_id, profile.profile_ruleset_version, profile.source_fingerprint)
            if existing is None: raise
            return self._same_or_conflict(existing, profile, signal_ids)
    def _same_or_conflict(self, existing, proposed, signal_ids):
        # effective_as_of records the original derivation context, not identity;
        # the same source set deliberately reuses that immutable snapshot.
        stored = (existing.summary_json, self.list_signal_ids(existing.id))
        incoming = (proposed.summary_json, sorted(set(signal_ids)))
        if canonical_json(stored) != canonical_json(incoming): raise ValueError("profile identity conflicts with immutable snapshot")
        return existing
