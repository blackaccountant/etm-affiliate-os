"""PostgreSQL-safe persistence primitives for M10A5 settlement linkage."""

from sqlalchemy import text

from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink


class AttributionPayoutSettlementLinkRepository:
    def __init__(self, db):
        self.db = db

    def acquire_payout_lock(self, payout_id: int) -> None:
        if self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": f"m10a5.payout-settlement:{payout_id}"},
            )

    def lock_earning_link(self, earning_link_id: str):
        return (
            self.db.query(AttributionEarningLink)
            .filter(AttributionEarningLink.id == earning_link_id)
            .with_for_update()
            .one_or_none()
        )

    def lock_earning(self, earning_id: int):
        return (
            self.db.query(AffiliateEarning)
            .filter(AffiliateEarning.id == earning_id)
            .with_for_update()
            .one_or_none()
        )

    def lock_payout(self, payout_id: int):
        return (
            self.db.query(AffiliatePayout)
            .filter(AffiliatePayout.id == payout_id)
            .with_for_update()
            .one_or_none()
        )

    def lock_completed_attempts(self, payout_id: int):
        return (
            self.db.query(AffiliatePayoutAttempt)
            .filter(
                AffiliatePayoutAttempt.payout_id == payout_id,
                AffiliatePayoutAttempt.status == "completed",
            )
            .with_for_update()
            .all()
        )

    def by_earning_link(self, earning_link_id: str):
        return (
            self.db.query(AttributionPayoutSettlementLink)
            .filter_by(attribution_earning_link_id=earning_link_id)
            .one_or_none()
        )

    def by_earning(self, earning_id: int):
        return (
            self.db.query(AttributionPayoutSettlementLink)
            .filter_by(affiliate_earning_id=earning_id)
            .one_or_none()
        )

    def create(self, link: AttributionPayoutSettlementLink):
        self.db.add(link)
        self.db.flush()
        return link
