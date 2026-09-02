"""Read-only M10A8 adjustment aggregation over an M10A6 snapshot."""
from sqlalchemy import and_, func, or_
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_financial_adjustment import AffiliateFinancialAdjustment
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink

class AttributionNetRealizedRevenueProjectionRepository:
    def __init__(self, db): self.db = db
    def adjustments_by_settled_lineage(self, records):
        records = tuple(records)
        if not records: return {}
        by_earning = {record.earning: record for record in records}
        rows = (self.db.query(AffiliateFinancialAdjustment.affiliate_earning_id, func.coalesce(func.sum(AffiliateFinancialAdjustment.adjustment_amount), 0))
            .join(AffiliateEarning, AffiliateEarning.id == AffiliateFinancialAdjustment.affiliate_earning_id)
            .outerjoin(AttributionPayoutSettlementLink, AttributionPayoutSettlementLink.id == AffiliateFinancialAdjustment.attribution_payout_settlement_link_id)
            .filter(AffiliateFinancialAdjustment.affiliate_earning_id.in_(tuple(by_earning)))
            .filter(AffiliateFinancialAdjustment.affiliate_program_id == AffiliateEarning.affiliate_program_id, AffiliateFinancialAdjustment.currency == AffiliateEarning.currency)
            .filter(or_(AffiliateFinancialAdjustment.affiliate_conversion_id.is_(None), AffiliateFinancialAdjustment.affiliate_conversion_id == AffiliateEarning.conversion_id))
            .filter(or_(AffiliateFinancialAdjustment.affiliate_payout_id.is_(None), AffiliateFinancialAdjustment.affiliate_payout_id == AffiliateEarning.payout_id))
            .filter(or_(AffiliateFinancialAdjustment.attribution_payout_settlement_link_id.is_(None), and_(AttributionPayoutSettlementLink.affiliate_earning_id == AffiliateEarning.id, AttributionPayoutSettlementLink.affiliate_payout_id == AffiliateEarning.payout_id)))
            .group_by(AffiliateFinancialAdjustment.affiliate_earning_id).all())
        return {earning_id: amount for earning_id, amount in rows}
