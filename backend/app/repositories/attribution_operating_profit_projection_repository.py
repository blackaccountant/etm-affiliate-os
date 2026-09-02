"""Read finalized M10A9E global allocations without changing authority."""

from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_global_cost_allocation import (
    AffiliateGlobalCostAllocationBatch,
    AffiliateGlobalCostAllocationLine,
)


class AttributionOperatingProfitProjectionRepository:
    def __init__(self, db):
        self.db = db

    def finalized_global_allocations_for_earnings(self, earning_ids):
        earning_ids = tuple(earning_ids)
        if not earning_ids:
            return ()
        return (
            self.db.query(
                AffiliateGlobalCostAllocationLine.affiliate_earning_id.label("earning"),
                AffiliateGlobalCostAllocationLine.amount.label("amount"),
                AffiliateGlobalCostAllocationBatch.currency.label("currency"),
                AffiliateCostEvent.currency.label("cost_currency"),
                AffiliateCostEvent.allocation_scope.label("allocation_scope"),
            )
            .join(
                AffiliateGlobalCostAllocationBatch,
                AffiliateGlobalCostAllocationBatch.id
                == AffiliateGlobalCostAllocationLine.allocation_batch_id,
            )
            .join(
                AffiliateCostEvent,
                AffiliateCostEvent.id
                == AffiliateGlobalCostAllocationBatch.affiliate_cost_event_id,
            )
            .filter(
                AffiliateGlobalCostAllocationLine.affiliate_earning_id.in_(earning_ids),
                AffiliateCostEvent.allocation_scope == "global",
            )
            .order_by(
                AffiliateGlobalCostAllocationBatch.id,
                AffiliateGlobalCostAllocationLine.affiliate_earning_id,
            )
            .all()
        )
