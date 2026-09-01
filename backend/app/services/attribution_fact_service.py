"""Internal append-only M10A attribution-fact service."""

from datetime import datetime, timezone

from app.attribution.contracts import aware_utc, fact_fingerprint, fact_references
from app.attribution.privacy import validate_privacy_safe_source
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_link import AffiliateLink
from app.models.attribution import AttributionClick, AttributionFact
from app.repositories.attribution_context_repository import AttributionContextRepository
from app.repositories.attribution_fact_repository import AttributionFactRepository
from app.repositories.attribution_publication_repository import AttributionPublicationRepository


class AttributionFactService:
    def __init__(self, db):
        self.db = db
        self.facts = AttributionFactRepository(db)
        self.contexts = AttributionContextRepository(db)
        self.publications = AttributionPublicationRepository(db)

    def append(self, *, fact_kind: str, source_namespace: str, source_event_key_digest: str,
               occurred_at: datetime, attribution_publication_id: str | None = None,
               attribution_context_id: str | None = None, attribution_click_id: str | None = None,
               affiliate_link_id: int | None = None, affiliate_conversion_id: int | None = None,
               supersedes_fact_id: str | None = None):
        namespace, digest = validate_privacy_safe_source(source_namespace, source_event_key_digest)
        occurred = aware_utc(occurred_at, "occurred_at")
        refs = fact_references(
            fact_kind=fact_kind,
            attribution_publication_id=attribution_publication_id,
            attribution_context_id=attribution_context_id,
            attribution_click_id=attribution_click_id,
            affiliate_link_id=affiliate_link_id,
            affiliate_conversion_id=affiliate_conversion_id,
            supersedes_fact_id=supersedes_fact_id,
        )
        if attribution_publication_id is not None and self.publications.get(attribution_publication_id) is None:
            raise ValueError("attribution publication does not exist")
        context = self.contexts.get(attribution_context_id) if attribution_context_id is not None else None
        if attribution_context_id is not None and context is None:
            raise ValueError("attribution context does not exist")
        link = self.db.get(AffiliateLink, affiliate_link_id) if affiliate_link_id is not None else None
        if affiliate_link_id is not None and link is None:
            raise ValueError("affiliate link does not exist")
        if context is not None and link is not None and context.affiliate_program_id != link.affiliate_program_id:
            raise ValueError("affiliate link program does not match attribution context")
        click = self.db.get(AttributionClick, attribution_click_id) if attribution_click_id is not None else None
        if attribution_click_id is not None and click is None:
            raise ValueError("attribution click does not exist")
        if click is not None and (click.attribution_context_id != attribution_context_id or click.affiliate_link_id != affiliate_link_id):
            raise ValueError("attribution click does not match fact context and link")
        conversion = self.db.get(AffiliateConversion, affiliate_conversion_id) if affiliate_conversion_id is not None else None
        if affiliate_conversion_id is not None and conversion is None:
            raise ValueError("affiliate conversion does not exist")
        if context is not None and conversion is not None and context.affiliate_program_id != conversion.affiliate_program_id:
            raise ValueError("affiliate conversion program does not match attribution context")
        if supersedes_fact_id is not None and self.facts.get(supersedes_fact_id) is None:
            raise ValueError("superseded attribution fact does not exist")
        fingerprint = fact_fingerprint(
            fact_kind=fact_kind, source_namespace=namespace, source_event_key_digest=digest,
            occurred_at=occurred, **{field: refs[field] for field in refs if field != "fact_kind"},
        )
        return self.facts.append_or_reuse(AttributionFact(
            fact_kind=refs["fact_kind"],
            source_namespace=namespace,
            source_event_key_digest=digest,
            source_fingerprint=fingerprint,
            attribution_publication_id=attribution_publication_id,
            attribution_context_id=attribution_context_id,
            attribution_click_id=attribution_click_id,
            affiliate_link_id=affiliate_link_id,
            affiliate_conversion_id=affiliate_conversion_id,
            supersedes_fact_id=supersedes_fact_id,
            occurred_at=occurred,
            recorded_at=datetime.now(timezone.utc),
        ))
