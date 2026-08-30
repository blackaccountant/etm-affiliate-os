"""Caller-owned immutable persistence for segments and revisions."""

from sqlalchemy.exc import IntegrityError
from app.audience.normalization import canonical_json
from app.models.audience import AudienceSegment, AudienceSegmentRevision


class AudienceSegmentRepository:
    def __init__(self, db): self.db = db
    def get_segment_by_id(self, segment_id): return self.db.get(AudienceSegment, segment_id)
    def get_segment_by_key(self, segment_key): return self.db.query(AudienceSegment).filter_by(segment_key=segment_key).one_or_none()
    def create_segment(self, segment):
        existing = self.get_segment_by_key(segment.segment_key)
        if existing is not None:
            if (existing.name, existing.description) != (segment.name, segment.description): raise ValueError("segment key conflicts with immutable identity")
            return existing
        try:
            with self.db.begin_nested(): self.db.add(segment); self.db.flush()
            return segment
        except IntegrityError:
            existing = self.get_segment_by_key(segment.segment_key)
            if existing is None: raise
            if (existing.name, existing.description) != (segment.name, segment.description): raise ValueError("segment key conflicts with immutable identity")
            return existing
    def get_revision_by_id(self, revision_id): return self.db.get(AudienceSegmentRevision, revision_id)
    def get_revision_by_identity(self, segment_id, ruleset, fingerprint):
        return self.db.query(AudienceSegmentRevision).filter_by(segment_id=segment_id, segment_ruleset_version=ruleset, definition_fingerprint=fingerprint).one_or_none()
    def create_revision_or_reuse(self, revision):
        existing = self.get_revision_by_identity(revision.segment_id, revision.segment_ruleset_version, revision.definition_fingerprint)
        if existing is not None: return self._same_or_conflict(existing, revision)
        try:
            with self.db.begin_nested(): self.db.add(revision); self.db.flush()
            return revision
        except IntegrityError:
            existing = self.get_revision_by_identity(revision.segment_id, revision.segment_ruleset_version, revision.definition_fingerprint)
            if existing is None: raise
            return self._same_or_conflict(existing, revision)
    @staticmethod
    def _same_or_conflict(existing, proposed):
        if canonical_json((existing.revision_number, existing.definition_json)) != canonical_json((proposed.revision_number, proposed.definition_json)):
            raise ValueError("segment revision identity conflicts with immutable definition")
        return existing
