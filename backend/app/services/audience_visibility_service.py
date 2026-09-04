"""Read-only aggregation service for UIF5D audience intelligence visibility."""

from app.repositories.audience_visibility_repository import AudienceVisibilityRepository


class AudienceVisibilityService:
    def __init__(self, repository: AudienceVisibilityRepository):
        self.repository = repository

    def snapshot(self, limit: int = 50) -> dict[str, list]:
        return {
            "profiles": self.repository.list_profiles(limit),
            "signals": self.repository.list_signals(limit),
            "qualifications": self.repository.list_qualifications(limit),
            "segments": self.repository.list_segments(limit),
            "segment_revisions": self.repository.list_segment_revisions(limit),
            "memberships": self.repository.list_memberships(limit),
        }
