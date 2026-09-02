"""Read finalized M10A9C allocation lines without changing allocation authority."""
from app.models.affiliate_cost_allocation import AffiliateCostAllocationBatch, AffiliateCostAllocationLine
from app.models.affiliate_cost_event import AffiliateCostEvent


class AttributionAllocatedContributionProfitProjectionRepository:
    def __init__(self, db):
        self.db = db

    def finalized_allocations_for_earnings(self, earning_ids):
        earning_ids = tuple(earning_ids)
        if not earning_ids:
            return ()
        return (
            self.db.query(
                AffiliateCostAllocationLine.affiliate_earning_id.label("earning"),
                AffiliateCostAllocationLine.amount.label("amount"),
                AffiliateCostAllocationBatch.currency.label("currency"),
                AffiliateCostEvent.allocation_scope.label("allocation_scope"),
                AffiliateCostEvent.currency.label("cost_currency"),
            )
            .join(
                AffiliateCostAllocationBatch,
                AffiliateCostAllocationBatch.id == AffiliateCostAllocationLine.allocation_batch_id,
            )
            .join(AffiliateCostEvent, AffiliateCostEvent.id == AffiliateCostAllocationBatch.affiliate_cost_event_id)
            .filter(
                AffiliateCostAllocationLine.affiliate_earning_id.in_(earning_ids),
                AffiliateCostEvent.allocation_scope == "shared",
            )
            .order_by(AffiliateCostAllocationBatch.id, AffiliateCostAllocationLine.affiliate_earning_id)
            .all()
        )
