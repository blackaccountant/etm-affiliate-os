"""Compose frozen M10A8 revenue with strictly eligible immutable M10A9A direct costs."""
from collections import defaultdict
from decimal import Decimal

from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest, ContributionProfitProjectionRow
from app.attribution.realized_revenue_projection_contracts import ALLOWED_DIMENSIONS
from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest
from app.repositories.attribution_contribution_profit_projection_repository import AttributionContributionProfitProjectionRepository
from app.services.attribution_net_realized_revenue_projection_service import AttributionNetRealizedRevenueProjectionService


_INTERNAL_DIMENSIONS = tuple(sorted(ALLOWED_DIMENSIONS))
_DIMENSION_CORRELATIONS = {
    "product_id": "product", "affiliate_program_id": "affiliate_program", "content_asset_id": "content_asset",
    "distribution_run_id": "distribution_run", "affiliate_link_id": "affiliate_link",
    "affiliate_conversion_id": "conversion", "affiliate_earning_id": "earning",
}


class AttributionContributionProfitProjectionService:
    def __init__(self, db):
        self.db = db
        self.costs = AttributionContributionProfitProjectionRepository(db)
        self._earning_grain_revenue_rows = None
        self._revenue_currency = None

    def project(self, request: ContributionProfitProjectionRequest | None = None) -> tuple[ContributionProfitProjectionRow, ...]:
        normalized = (request or ContributionProfitProjectionRequest()).normalized()
        # This must be the first SQL-producing operation in a fresh caller-owned session.
        if self._earning_grain_revenue_rows is None:
            self._earning_grain_revenue_rows = AttributionNetRealizedRevenueProjectionService(self.db).project(
                NetRealizedRevenueProjectionRequest(_INTERNAL_DIMENSIONS, normalized.currency)
            )
            self._revenue_currency = normalized.currency
        elif normalized.currency != self._revenue_currency:
            raise ValueError("a fresh Session is required for a different contribution-profit currency filter")
        revenue_rows = self._earning_grain_revenue_rows
        lineages, conversions = self._lineages(revenue_rows)
        settlement = self.costs.settlements_by_earning(lineages)
        attributable = defaultdict(lambda: Decimal("0"))
        seen = set()
        for event in self.costs.direct_cost_candidates(lineages, conversions):
            if event.id in seen or not self._eligible(event, lineages, conversions, settlement):
                continue
            earning = event.affiliate_earning_id or conversions[event.affiliate_conversion_id]
            attributable[earning] += Decimal(str(event.amount))
            seen.add(event.id)
        buckets = defaultdict(lambda: [Decimal("0"), Decimal("0")])
        for earning, lineage in lineages.items():
            dimensions = tuple((name, lineage["dimensions"][name]) for name in normalized.dimensions)
            bucket = buckets[(lineage["currency"], dimensions)]
            bucket[0] += lineage["revenue"]
            bucket[1] += attributable[earning]
        return tuple(
            ContributionProfitProjectionRow(currency, revenue, cost, revenue - cost, dimensions)
            for (currency, dimensions), (revenue, cost) in sorted(
                buckets.items(), key=lambda item: (item[0][0], tuple((name, str(value)) for name, value in item[0][1]))
            )
        )

    @staticmethod
    def _lineages(rows):
        lineages, conversions = {}, {}
        for row in rows:
            dimensions = dict(row.dimensions)
            earning, conversion = dimensions["earning"], dimensions["conversion"]
            if earning is None or conversion is None or earning in lineages or conversion in conversions:
                raise ValueError("M10A8 earning-grain revenue lineage is ambiguous")
            lineages[earning] = {"currency": row.currency, "revenue": row.net_realized_commission, "dimensions": dimensions}
            conversions[conversion] = earning
        return lineages, conversions

    @staticmethod
    def _eligible(event, lineages, conversions, settlements):
        if event.content_generation_run_id is not None or event.outreach_provider_dispatch_id is not None:
            return False
        earnings = []
        if event.affiliate_earning_id is not None:
            if event.affiliate_earning_id not in lineages:
                return False
            earnings.append(event.affiliate_earning_id)
        if event.affiliate_conversion_id is not None:
            earning = conversions.get(event.affiliate_conversion_id)
            if earning is None:
                return False
            earnings.append(earning)
        if not earnings or len(set(earnings)) != 1:
            return False
        earning = earnings[0]
        lineage = lineages[earning]
        if event.currency != lineage["currency"]:
            return False
        for field, dimension in _DIMENSION_CORRELATIONS.items():
            value = getattr(event, field)
            if value is not None and value != lineage["dimensions"][dimension]:
                return False
        settlement = settlements.get(earning)
        if settlement is None:
            return False
        return (
            (event.affiliate_payout_id is None or event.affiliate_payout_id == settlement.affiliate_payout_id)
            and (event.affiliate_payout_attempt_id is None or event.affiliate_payout_attempt_id == settlement.affiliate_payout_attempt_id)
        )
