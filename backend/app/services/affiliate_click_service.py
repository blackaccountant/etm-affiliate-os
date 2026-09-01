"""
Affiliate Click Service

Records and retrieves clicks
for affiliate tracking links.
"""

from sqlalchemy.orm import Session

from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_link import AffiliateLink


class AffiliateClickService:

    def __init__(self, db: Session):
        self.db = db

    def record_click(
        self,
        tracking_code: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ):
        click = self._record_click_uncommitted(
            tracking_code=tracking_code,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.commit()
        self.db.refresh(click)
        return click

    def _record_click_uncommitted(
        self,
        tracking_code: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        *,
        attribution_click_id: str | None = None,
    ):
        """Create and flush one legacy click without committing or rolling back."""
        link = (
            self.db.query(AffiliateLink)
            .filter(AffiliateLink.tracking_code == tracking_code)
            .first()
        )
        if not link:
            raise ValueError("Affiliate link not found")
        if not link.is_active:
            raise ValueError("Affiliate link is inactive")
        if attribution_click_id is not None:
            existing = self.db.query(AffiliateClick).filter_by(
                attribution_click_id=attribution_click_id,
            ).one_or_none()
            if existing is not None:
                return existing
        click = AffiliateClick(
            affiliate_link_id=link.id,
            attribution_click_id=attribution_click_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.db.add(click)
        self.db.flush()
        return click

    def get_clicks(
        self,
        affiliate_link_id: int,
    ):

        return (
            self.db.query(AffiliateClick)
            .filter(
                AffiliateClick.affiliate_link_id
                == affiliate_link_id
            )
            .order_by(
                AffiliateClick.created_at.desc()
            )
            .all()
        )

    def count_clicks(
        self,
        affiliate_link_id: int,
    ):

        return (
            self.db.query(AffiliateClick)
            .filter(
                AffiliateClick.affiliate_link_id
                == affiliate_link_id
            )
            .count()
        )
