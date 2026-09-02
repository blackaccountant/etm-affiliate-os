"""Compose frozen M10A9B contribution profit with finalized M10A9C allocations."""
from collections import defaultdict
from decimal import Decimal

from app.attribution.allocated_contribution_profit_projection_contracts import (
    AllocatedContributionProfitProjectionRequest,
    AllocatedContributionProfitProjectionRow,
)
from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest
from app.attribution.realized_revenue_projection_contracts import ALLOWED_DIMENSIONS
from app.repositories.attribution_allocated_contribution_profit_projection_repository import (
    AttributionAllocatedContributionProfitProjectionRepository,
)
from app.services.attribution_contribution_profit_projection_service import (
    AttributionContributionProfitProjectionService,
)


_INTERNAL_DIMENSIONS = tuple(sorted(ALLOWED_DIMENSIONS))


class AttributionAllocatedContributionProfitProjectionService:
    def __init__(self, db):
        self.db = db
        self.allocations = AttributionAllocatedContributionProfitProjectionRepository(db)
        self._earning_grain_upstream = None
        self._upstream_currency = None

    def project(
        self, request: AllocatedContributionProfitProjectionRequest | None = None,
    ) -> tuple[AllocatedContributionProfitProjectionRow, ...]:
        normalized = (request or AllocatedContributionProfitProjectionRequest()).normalized()
        if self._earning_grain_upstream is None:
            # This must remain the first SQL-producing operation in a fresh caller-owned Session.
            upstream_rows = AttributionContributionProfitProjectionService(self.db).project(
                ContributionProfitProjectionRequest(_INTERNAL_DIMENSIONS, normalized.currency)
            )
            self._earning_grain_upstream = self._upstream_by_earning(upstream_rows)
            self._upstream_currency = normalized.currency
        elif normalized.currency != self._upstream_currency:
            raise ValueError("a fresh Session is required for a different allocated contribution-profit currency filter")
        by_earning = self._earning_grain_upstream
        allocated = defaultdict(lambda: Decimal("0"))
        for line in self.allocations.finalized_allocations_for_earnings(by_earning):
            upstream = by_earning.get(line.earning)
            if upstream is None:
                continue
            if line.allocation_scope != "shared" or line.cost_currency != line.currency:
                raise ValueError("M10A9C finalized allocation authority is inconsistent")
            if line.currency != upstream.currency:
                raise ValueError("M10A9C allocation currency contradicts M10A9B revenue currency")
            allocated[line.earning] += Decimal(str(line.amount))

        buckets = defaultdict(lambda: [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")])
        for earning, row in by_earning.items():
            source_dimensions = dict(row.dimensions)
            dimensions = tuple((name, source_dimensions[name]) for name in normalized.dimensions)
            bucket = buckets[(row.currency, dimensions)]
            bucket[0] += row.net_realized_commission
            bucket[1] += row.directly_attributable_cost
            bucket[2] += row.contribution_profit
            bucket[3] += allocated[earning]

        return tuple(
            AllocatedContributionProfitProjectionRow(
                currency=currency,
                net_realized_commission=revenue,
                directly_attributable_cost=direct_cost,
                contribution_profit=contribution_profit,
                allocated_shared_cost=shared_cost,
                allocated_contribution_profit=contribution_profit - shared_cost,
                dimensions=dimensions,
            )
            for (currency, dimensions), (revenue, direct_cost, contribution_profit, shared_cost) in sorted(
                buckets.items(),
                key=lambda item: (item[0][0], tuple((name, str(value)) for name, value in item[0][1])),
            )
        )

    @staticmethod
    def _upstream_by_earning(rows):
        result = {}
        for row in rows:
            earning = dict(row.dimensions).get("earning")
            if earning is None or earning in result:
                raise ValueError("M10A9B earning-grain contribution-profit lineage is ambiguous")
            result[earning] = row
        return result
