"""Persistence and settled-lineage reads for global-cost allocation authority."""

from sqlalchemy import func

from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_global_cost_allocation import (
    AffiliateGlobalCostAllocationBatch,
    AffiliateGlobalCostAllocationLine,
)
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution_payout_settlement_link import (
    AttributionPayoutSettlementLink,
)


class AffiliateGlobalCostAllocationRepository:
    def __init__(self, db):
        self.db = db

    def lock_cost_event(self, event_id):
        return (
            self.db.query(AffiliateCostEvent)
            .filter_by(id=event_id)
            .with_for_update()
            .one_or_none()
        )

    def batch_by_cost_event(self, event_id):
        return (
            self.db.query(AffiliateGlobalCostAllocationBatch)
            .filter_by(affiliate_cost_event_id=event_id)
            .one_or_none()
        )

    def batch_by_source(self, namespace, digest):
        return (
            self.db.query(AffiliateGlobalCostAllocationBatch)
            .filter_by(
                source_namespace=namespace,
                source_event_digest=digest,
            )
            .one_or_none()
        )

    def lines_for_batch(self, batch_id):
        return (
            self.db.query(AffiliateGlobalCostAllocationLine)
            .filter_by(allocation_batch_id=batch_id)
            .order_by(AffiliateGlobalCostAllocationLine.affiliate_earning_id)
            .all()
        )

    def add(self, batch, lines):
        self.db.add(batch)
        self.db.flush()

        for line in lines:
            line.allocation_batch_id = batch.id
            self.db.add(line)

        self.db.flush()
        return batch

    def settled_earnings(self, earning_ids):
        earning_ids = tuple(earning_ids)

        if not earning_ids:
            return ()

        completed_attempts = (
            self.db.query(func.count(AffiliatePayoutAttempt.id))
            .filter(
                AffiliatePayoutAttempt.payout_id
                == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed",
            )
            .correlate(AttributionPayoutSettlementLink)
            .scalar_subquery()
        )

        return (
            self.db.query(
                AffiliateEarning.id.label("earning"),
                AffiliateEarning.currency.label("currency"),
            )
            .select_from(AttributionPayoutSettlementLink)
            .join(
                AttributionEarningLink,
                AttributionEarningLink.id
                == AttributionPayoutSettlementLink.attribution_earning_link_id,
            )
            .join(
                AffiliateEarning,
                (
                    AffiliateEarning.id
                    == AttributionPayoutSettlementLink.affiliate_earning_id
                )
                & (
                    AffiliateEarning.id
                    == AttributionEarningLink.affiliate_earning_id
                ),
            )
            .join(
                AffiliatePayout,
                AffiliatePayout.id
                == AttributionPayoutSettlementLink.affiliate_payout_id,
            )
            .join(
                AffiliatePayoutAttempt,
                AffiliatePayoutAttempt.id
                == AttributionPayoutSettlementLink.affiliate_payout_attempt_id,
            )
            .filter(
                AffiliateEarning.id.in_(earning_ids),
                AffiliateEarning.payout_id
                == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliateEarning.status == "paid",
                AffiliatePayout.status == "paid",
                AffiliatePayoutAttempt.payout_id
                == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed",
                completed_attempts == 1,
            )
            .order_by(AffiliateEarning.id)
            .all()
        )
