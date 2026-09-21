"""Read-only GLR1 lineage resolution and provider-bound WordPress rendering."""

import re

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.affiliate_link import AffiliateLink
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.distribution_run import DistributionRun


class PilotCmsPublicationService:
    def __init__(self, db: Session):
        self.db = db

    def tracking_code_for_run(self, run_id: str) -> str:
        if self.db.get(DistributionRun, run_id) is None:
            raise ValueError("distribution run does not exist")
        publications = self.db.query(AttributionPublication).filter_by(distribution_run_id=run_id).all()
        if len(publications) != 1:
            raise ValueError("distribution run attribution publication must be unique")
        contexts = self.db.query(AttributionContext).filter_by(attribution_publication_id=publications[0].id).all()
        if len(contexts) != 1:
            raise ValueError("distribution run attribution context must be unique")
        context = contexts[0]
        links = self.db.query(AffiliateLink).filter_by(attribution_context_id=context.id, is_active=True).all()
        if len(links) != 1:
            raise ValueError("active affiliate link must be unique")
        link = links[0]
        if link.affiliate_program_id != context.affiliate_program_id:
            raise ValueError("affiliate link program conflicts with attribution context")
        tracking_code = (link.tracking_code or "").strip()
        if not tracking_code:
            raise ValueError("affiliate tracking code is unavailable")
        return tracking_code

    def render_wordpress_body(self, run: DistributionRun) -> str:
        origin = (settings.PUBLIC_API_BASE_URL or "").strip().rstrip("/")
        if not origin:
            raise ValueError("PUBLIC_API_BASE_URL is not configured")
        url = f"{origin}/affiliate-links/go/{self.tracking_code_for_run(run.id)}"
        source = run.prepared_content_body or ""
        for pattern in (r"\{\{\s*(?:affiliate|tracked)[^\n}]*?(?:link|url)\s*\}\}", r"\{\s*(?:affiliate|tracked)[^\n}]*?(?:link|url)\s*\}", r"<\s*affiliate-cta\s*>", r"<!--\s*affiliate-link\s*-->"):
            rendered = re.sub(pattern, f'<p><a href="{url}">Learn more</a></p>', source, flags=re.IGNORECASE)
            if rendered != source:
                return rendered
        return f"{source.rstrip()}\n\n<p><a href=\"{url}\">Learn more</a></p>" if source else f'<p><a href="{url}">Learn more</a></p>'
