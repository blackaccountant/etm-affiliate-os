"""Read primitives for M10A9B; this repository never changes cost authority."""
from sqlalchemy import or_

from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink


class AttributionContributionProfitProjectionRepository:
    def __init__(self, db):
        self.db = db

    def direct_cost_candidates(self, earning_ids, conversion_ids):
        return (
            self.db.query(AffiliateCostEvent)
            .filter(AffiliateCostEvent.allocation_scope == "direct")
            .filter(or_(AffiliateCostEvent.affiliate_earning_id.in_(tuple(earning_ids)), AffiliateCostEvent.affiliate_conversion_id.in_(tuple(conversion_ids))))
            .order_by(AffiliateCostEvent.id)
            .all()
        )

    def settlements_by_earning(self, earning_ids):
        rows = self.db.query(AttributionPayoutSettlementLink).filter(AttributionPayoutSettlementLink.affiliate_earning_id.in_(tuple(earning_ids))).all()
        return {row.affiliate_earning_id: row for row in rows}
