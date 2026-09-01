"""Internal fail-closed creation of immutable attribution contexts."""

from datetime import datetime, timezone

from app.attribution.contracts import context_fingerprint
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext
from app.models.publishing_queue import PublishingQueue
from app.repositories.attribution_context_repository import AttributionContextRepository
from app.repositories.attribution_publication_repository import AttributionPublicationRepository


class AttributionContextService:
    def __init__(self, db):
        self.db = db
        self.contexts = AttributionContextRepository(db)
        self.publications = AttributionPublicationRepository(db)

    def create(self, *, affiliate_program_id: int, attribution_publication_id: str):
        program = self.db.get(AffiliateProgram, affiliate_program_id)
        if program is None:
            raise ValueError("affiliate program does not exist")
        publication = self.publications.get(attribution_publication_id)
        if publication is None:
            raise ValueError("attribution publication does not exist")
        if publication.legacy_publishing_queue_id is not None:
            queue = self.db.get(PublishingQueue, publication.legacy_publishing_queue_id)
            asset = self.db.get(AffiliateContentAsset, queue.content_asset_id) if queue is not None else None
            if asset is None:
                raise ValueError("legacy publication content authority is incomplete")
            if asset.product_id != program.product_id:
                raise ValueError("legacy publication product does not match affiliate program product")
        fingerprint = context_fingerprint(
            affiliate_program_id=program.id, attribution_publication_id=publication.id,
        )
        return self.contexts.create_or_reuse(AttributionContext(
            affiliate_program_id=program.id,
            attribution_publication_id=publication.id,
            context_fingerprint=fingerprint,
            created_at=datetime.now(timezone.utc),
        ))
