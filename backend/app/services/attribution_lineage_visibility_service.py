"""Read-only aggregation service for UIF5E attribution lineage visibility."""

from app.repositories.attribution_lineage_visibility_repository import (
    AttributionLineageVisibilityRepository,
)


class AttributionLineageVisibilityService:
    def __init__(self, repository: AttributionLineageVisibilityRepository):
        self.repository = repository

    def snapshot(self, limit: int = 50) -> dict[str, list]:
        return {
            "publications": self.repository.list_publications(limit),
            "contexts": self.repository.list_contexts(limit),
            "clicks": self.repository.list_clicks(limit),
            "facts": self.repository.list_facts(limit),
            "earning_links": self.repository.list_earning_links(limit),
            "settlement_links": self.repository.list_settlement_links(limit),
        }
