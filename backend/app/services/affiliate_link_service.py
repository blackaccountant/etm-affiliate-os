"""
Affiliate Link Service

Handles creation and management
of affiliate tracking links.
"""


import secrets
import string

from sqlalchemy.orm import Session

from app.models.affiliate_link import AffiliateLink



class AffiliateLinkService:


    def __init__(
        self,
        db: Session
    ):

        self.db = db



    def generate_tracking_code(
        self,
        length=12
    ):

        chars = (
            string.ascii_letters
            +
            string.digits
        )

        return (
            "".join(
                secrets.choice(chars)
                for _ in range(length)
            )
        )



    def create_link(
        self,
        affiliate_program_id: int,
        name: str,
        destination_url: str,
        content_asset_id: int | None = None,
    ):
        link = self._create_link_uncommitted(
            affiliate_program_id=affiliate_program_id,
            name=name,
            destination_url=destination_url,
            content_asset_id=content_asset_id,
        )
        self.db.commit()
        self.db.refresh(link)
        return link


    def _create_link_uncommitted(
        self,
        affiliate_program_id: int,
        name: str,
        destination_url: str,
        content_asset_id: int | None = None,
        *,
        attribution_context_id: str | None = None,
        tracking_code: str | None = None,
    ):
        """Create and flush a link without owning the caller's transaction."""
        link = AffiliateLink(
            affiliate_program_id=affiliate_program_id,
            content_asset_id=content_asset_id,
            attribution_context_id=attribution_context_id,
            name=name,
            destination_url=destination_url,
            tracking_code=tracking_code or self.generate_tracking_code(),
            is_active=True,
        )
        self.db.add(link)
        self.db.flush()
        return link



    def get_by_tracking_code(
        self,
        tracking_code: str
    ):

        return (
            self.db.query(
                AffiliateLink
            )
            .filter(
                AffiliateLink.tracking_code
                ==
                tracking_code
            )
            .first()
        )



    def deactivate(
        self,
        link_id:int
    ):

        link = (
            self.db.query(
                AffiliateLink
            )
            .filter(
                AffiliateLink.id
                ==
                link_id
            )
            .first()
        )


        if not link:
            raise ValueError(
                "Affiliate link not found"
            )


        link.is_active=False

        self.db.commit()

        return link
