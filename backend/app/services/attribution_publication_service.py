"""Internal creation of one strong attribution-publication authority."""

from datetime import datetime, timezone

from app.models.attribution import AttributionPublication
from app.models.distribution_run import DistributionRun
from app.models.publishing_queue import PublishingQueue
from app.repositories.attribution_publication_repository import AttributionPublicationRepository


class AttributionPublicationService:
    def __init__(self, db):
        self.db = db
        self.publications = AttributionPublicationRepository(db)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def bind_legacy(self, publishing_queue_id: int):
        if not isinstance(publishing_queue_id, int) or publishing_queue_id < 1:
            raise ValueError("publishing_queue_id must be a positive integer")
        if self.db.get(PublishingQueue, publishing_queue_id) is None:
            raise ValueError("publishing queue authority does not exist")
        return self.publications.create_or_reuse(AttributionPublication(
            legacy_publishing_queue_id=publishing_queue_id, distribution_run_id=None, created_at=self._now(),
        ))

    def bind_distribution(self, distribution_run_id: str):
        if self.db.get(DistributionRun, distribution_run_id) is None:
            raise ValueError("distribution run authority does not exist")
        return self.publications.create_or_reuse(AttributionPublication(
            legacy_publishing_queue_id=None, distribution_run_id=distribution_run_id, created_at=self._now(),
        ))
