"""Locked persistence and settled-lineage reads for shared-cost allocation authority."""
from sqlalchemy import func

from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_cost_allocation import AffiliateCostAllocationBatch, AffiliateCostAllocationLine
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionFact, AttributionPublication
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.models.product import Product


class AffiliateCostAllocationRepository:
    def __init__(self, db):
        self.db = db

    def lock_cost_event(self, event_id):
        return self.db.query(AffiliateCostEvent).filter_by(id=event_id).with_for_update().one_or_none()

    def batch_by_cost_event(self, event_id):
        return self.db.query(AffiliateCostAllocationBatch).filter_by(affiliate_cost_event_id=event_id).one_or_none()

    def batch_by_source(self, namespace, digest):
        return self.db.query(AffiliateCostAllocationBatch).filter_by(source_namespace=namespace, source_event_digest=digest).one_or_none()

    def lines_for_batch(self, batch_id):
        return self.db.query(AffiliateCostAllocationLine).filter_by(allocation_batch_id=batch_id).order_by(AffiliateCostAllocationLine.affiliate_earning_id).all()

    def add(self, batch, lines):
        self.db.add(batch)
        self.db.flush()
        for line in lines:
            line.allocation_batch_id = batch.id
            self.db.add(line)
        self.db.flush()
        return batch

    def settled_lineages(self, earning_ids):
        earning_ids = tuple(earning_ids)
        if not earning_ids:
            return ()
        completed_attempts = (
            self.db.query(func.count(AffiliatePayoutAttempt.id))
            .filter(
                AffiliatePayoutAttempt.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed",
            )
            .correlate(AttributionPayoutSettlementLink)
            .scalar_subquery()
        )
        return (
            self.db.query(
                AffiliateEarning.id.label("earning"),
                AffiliateEarning.currency.label("currency"),
                AffiliateConversion.id.label("conversion"),
                AffiliateProgram.id.label("affiliate_program"),
                Product.id.label("product"),
                AffiliateLink.id.label("affiliate_link"),
                AffiliateLink.content_asset_id.label("content_asset"),
                AttributionPublication.distribution_run_id.label("distribution_run"),
                AttributionPayoutSettlementLink.affiliate_payout_id.label("payout"),
                AttributionPayoutSettlementLink.affiliate_payout_attempt_id.label("payout_attempt"),
            )
            .select_from(AttributionPayoutSettlementLink)
            .join(AttributionEarningLink, AttributionEarningLink.id == AttributionPayoutSettlementLink.attribution_earning_link_id)
            .join(AffiliateEarning, (AffiliateEarning.id == AttributionPayoutSettlementLink.affiliate_earning_id) & (AffiliateEarning.id == AttributionEarningLink.affiliate_earning_id))
            .join(AffiliatePayout, AffiliatePayout.id == AttributionPayoutSettlementLink.affiliate_payout_id)
            .join(AffiliatePayoutAttempt, AffiliatePayoutAttempt.id == AttributionPayoutSettlementLink.affiliate_payout_attempt_id)
            .outerjoin(AffiliateConversion, (AffiliateConversion.id == AttributionEarningLink.affiliate_conversion_id) & (AffiliateConversion.id == AffiliateEarning.conversion_id))
            .join(AffiliateProgram, AffiliateProgram.id == AffiliateEarning.affiliate_program_id)
            .outerjoin(Product, Product.id == AffiliateProgram.product_id)
            .outerjoin(AffiliateLink, AffiliateLink.id == AffiliateConversion.affiliate_link_id)
            .outerjoin(AttributionFact, AttributionFact.id == AttributionEarningLink.attribution_fact_id)
            .outerjoin(AttributionContext, AttributionContext.id == AttributionFact.attribution_context_id)
            .outerjoin(AttributionPublication, AttributionPublication.id == AttributionContext.attribution_publication_id)
            .filter(
                AffiliateEarning.id.in_(earning_ids),
                AffiliateEarning.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliateEarning.status == "paid",
                AffiliatePayout.status == "paid",
                AffiliatePayoutAttempt.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed",
                completed_attempts == 1,
            )
            .order_by(AffiliateEarning.id)
            .all()
        )
