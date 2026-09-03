"""Read-only timestamp lookup over frozen payout-settlement authority."""

from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink


class OperatingProfitEvidenceRepository:
    def __init__(self, db):
        self.db = db

    def observed_at_by_settlement_link(self, settlement_link_ids):
        values = tuple(settlement_link_ids)
        if not values:
            return ()
        return self.db.query(
            AttributionPayoutSettlementLink.id.label("settlement_link"),
            AttributionPayoutSettlementLink.observed_at.label("observed_at"),
        ).filter(AttributionPayoutSettlementLink.id.in_(values)).all()
