"""Locking and lookup primitives used only by the M10A3 public bridge."""

from sqlalchemy import text

from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.attribution import AttributionClick, AttributionContext


class AttributionBridgeRepository:
    def __init__(self, db):
        self.db = db

    def acquire_identity_lock(self, namespace: str, digest: str) -> None:
        if self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": f"{namespace}:{digest}"},
            )

    def get_context(self, context_id: str):
        return self.db.get(AttributionContext, context_id)

    def get_link(self, link_id: int):
        return self.db.get(AffiliateLink, link_id)

    def lock_link(self, link_id: int):
        return (
            self.db.query(AffiliateLink)
            .filter(AffiliateLink.id == link_id)
            .with_for_update()
            .one_or_none()
        )

    def link_by_tracking_code(self, tracking_code: str):
        return (
            self.db.query(AffiliateLink)
            .filter(AffiliateLink.tracking_code == tracking_code)
            .first()
        )

    def bind_link_context(self, link_id: int, context_id: str):
        link = self.lock_link(link_id)
        if link is None:
            raise ValueError("affiliate link does not exist")
        if link.attribution_context_id is not None:
            if link.attribution_context_id != context_id:
                raise AttributionBridgeConflict(
                    "affiliate link is already bound to a different attribution context"
                )
            return link
        link.attribution_context_id = context_id
        self.db.flush()
        return link

    def attribution_click_by_source(self, namespace: str, digest: str):
        return self.db.query(AttributionClick).filter_by(
            source_namespace=namespace, source_event_key_digest=digest,
        ).one_or_none()

    def attribution_click_by_key(self, click_key: str):
        return self.db.query(AttributionClick).filter_by(click_key=click_key).one_or_none()

    def legacy_click_by_attribution_click(self, attribution_click_id: str):
        return self.db.query(AffiliateClick).filter_by(
            attribution_click_id=attribution_click_id,
        ).one_or_none()

    def conversion_by_external(self, program_id: int, external_conversion_id: str):
        return self.db.query(AffiliateConversion).filter_by(
            affiliate_program_id=program_id,
            external_conversion_id=external_conversion_id,
        ).one_or_none()

    def earning_by_conversion(self, conversion_id: int):
        return self.db.query(AffiliateEarning).filter_by(conversion_id=conversion_id).one_or_none()
