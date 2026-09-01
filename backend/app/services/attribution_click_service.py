"""Internal privacy-safe attribution-click ingestion."""

from datetime import datetime, timezone

from app.attribution.contracts import aware_utc, click_fingerprint, click_key_for_source
from app.attribution.privacy import validate_privacy_safe_source
from app.models.affiliate_link import AffiliateLink
from app.models.attribution import AttributionClick
from app.repositories.attribution_click_repository import AttributionClickRepository
from app.repositories.attribution_context_repository import AttributionContextRepository


class AttributionClickService:
    def __init__(self, db):
        self.db = db
        self.clicks = AttributionClickRepository(db)
        self.contexts = AttributionContextRepository(db)

    def record(self, *, attribution_context_id: str, affiliate_link_id: int,
               source_namespace: str, source_event_key_digest: str, occurred_at: datetime):
        namespace, digest = validate_privacy_safe_source(source_namespace, source_event_key_digest)
        occurred = aware_utc(occurred_at, "occurred_at")
        context = self.contexts.get(attribution_context_id)
        link = self.db.get(AffiliateLink, affiliate_link_id)
        if context is None:
            raise ValueError("attribution context does not exist")
        if link is None:
            raise ValueError("affiliate link does not exist")
        if link.affiliate_program_id != context.affiliate_program_id:
            raise ValueError("affiliate link program does not match attribution context")
        click_key = click_key_for_source(namespace, digest)
        fingerprint = click_fingerprint(
            click_key=click_key, attribution_context_id=context.id, affiliate_link_id=link.id,
            source_namespace=namespace, source_event_key_digest=digest, occurred_at=occurred,
        )
        return self.clicks.create_or_reuse(AttributionClick(
            click_key=click_key,
            attribution_context_id=context.id,
            affiliate_link_id=link.id,
            source_namespace=namespace,
            source_event_key_digest=digest,
            source_fingerprint=fingerprint,
            occurred_at=occurred,
            recorded_at=datetime.now(timezone.utc),
        ))
