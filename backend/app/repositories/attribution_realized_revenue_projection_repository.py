"""Read-only PostgreSQL query primitives for M10A6 settled commission projections."""

from sqlalchemy import func, text

from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionClick, AttributionContext, AttributionFact, AttributionPublication
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.models.product import Product


class AttributionRealizedRevenueProjectionRepository:
    """Produces only consistent snapshots; it contains no persistence methods."""

    def __init__(self, db):
        self.db = db

    def _begin_consistent_read(self) -> None:
        if self.db.bind.dialect.name == "postgresql":
            self.db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))

    def settled_lineage(self, *, currency: str | None):
        self._begin_consistent_read()
        completed_attempts = (
            self.db.query(func.count(AffiliatePayoutAttempt.id))
            .filter(
                AffiliatePayoutAttempt.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed",
            )
            .correlate(AttributionPayoutSettlementLink)
            .scalar_subquery()
        )
        query = (
            self.db.query(
                AttributionPayoutSettlementLink.id.label("settlement_link"),
                AffiliateEarning.id.label("earning"), AffiliateConversion.id.label("conversion"),
                AffiliateProgram.id.label("affiliate_program"), Product.id.label("product"),
                AffiliateLink.id.label("affiliate_link"), AffiliateLink.content_asset_id.label("content_asset"),
                AttributionContext.id.label("attribution_context"), AttributionClick.id.label("attribution_click"),
                AttributionPublication.id.label("attribution_publication"),
                AttributionPublication.legacy_publishing_queue_id.label("publishing_authority"),
                AttributionPublication.distribution_run_id.label("distribution_run"),
                AffiliateEarning.currency.label("currency"), AffiliateEarning.commission_amount.label("commission_amount"),
            )
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
            .outerjoin(AttributionClick, AttributionClick.id == AttributionFact.attribution_click_id)
            .outerjoin(AttributionPublication, AttributionPublication.id == AttributionContext.attribution_publication_id)
            .filter(
                AffiliateEarning.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliateEarning.status == "paid", AffiliatePayout.status == "paid",
                AffiliatePayoutAttempt.payout_id == AttributionPayoutSettlementLink.affiliate_payout_id,
                AffiliatePayoutAttempt.status == "completed", completed_attempts == 1,
            )
        )
        if currency is not None:
            query = query.filter(AffiliateEarning.currency == currency)
        return query.all()
