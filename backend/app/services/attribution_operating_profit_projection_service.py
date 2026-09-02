"""Compose frozen M10A9D with finalized M10A9E global allocations."""

from collections import defaultdict
from decimal import Decimal

from app.attribution.allocated_contribution_profit_projection_contracts import (
    AllocatedContributionProfitProjectionRequest,
)
from app.attribution.operating_profit_projection_contracts import (
    OperatingProfitProjectionRequest,
    OperatingProfitProjectionRow,
)
from app.attribution.realized_revenue_projection_contracts import ALLOWED_DIMENSIONS
from app.repositories.attribution_operating_profit_projection_repository import (
    AttributionOperatingProfitProjectionRepository,
)
from app.services.attribution_allocated_contribution_profit_projection_service import (
    AttributionAllocatedContributionProfitProjectionService,
)


_INTERNAL_DIMENSIONS = tuple(sorted(ALLOWED_DIMENSIONS))


class AttributionOperatingProfitProjectionService:
    def __init__(self, db):
        self.db = db
        self.allocations = AttributionOperatingProfitProjectionRepository(db)
        self._earning_grain_upstream = None
        self._upstream_currency = None

    def project(
        self, request: OperatingProfitProjectionRequest | None = None,
    ) -> tuple[OperatingProfitProjectionRow, ...]:
        normalized = (request or OperatingProfitProjectionRequest()).normalized()
        if self._earning_grain_upstream is None:
            # This must remain the first SQL-producing operation in a fresh caller-owned Session.
            rows = AttributionAllocatedContributionProfitProjectionService(self.db).project(
                AllocatedContributionProfitProjectionRequest(
                    _INTERNAL_DIMENSIONS, normalized.currency,
                )
            )
            self._earning_grain_upstream = self._upstream_by_earning(rows)
            self._upstream_currency = normalized.currency
        elif normalized.currency != self._upstream_currency:
            raise ValueError(
                "a fresh Session is required for a different operating-profit currency filter"
            )

        by_earning = self._earning_grain_upstream
        allocated = defaultdict(lambda: Decimal("0"))
        for line in self.allocations.finalized_global_allocations_for_earnings(by_earning):
            upstream = by_earning.get(line.earning)
            if upstream is None:
                continue
            if line.allocation_scope != "global" or line.cost_currency != line.currency:
                raise ValueError("M10A9E finalized allocation authority is inconsistent")
            if line.currency != upstream.currency:
                raise ValueError("M10A9E allocation currency contradicts M10A9D revenue currency")
            allocated[line.earning] += Decimal(str(line.amount))

        buckets = defaultdict(lambda: [Decimal("0")] * 5)
        for earning, row in by_earning.items():
            source = dict(row.dimensions)
            dimensions = tuple((name, source[name]) for name in normalized.dimensions)
            bucket = buckets[(row.currency, dimensions)]
            bucket[0] += row.net_realized_commission
            bucket[1] += row.directly_attributable_cost
            bucket[2] += row.contribution_profit
            bucket[3] += row.allocated_shared_cost
            bucket[4] += allocated[earning]

        return tuple(
            OperatingProfitProjectionRow(
                currency=currency,
                net_realized_commission=revenue,
                directly_attributable_cost=direct_cost,
                contribution_profit=contribution,
                allocated_shared_cost=shared,
                allocated_contribution_profit=allocated_contribution,
                allocated_global_cost=global_cost,
                operating_profit=allocated_contribution - global_cost,
                dimensions=dimensions,
            )
            for (currency, dimensions), (
                revenue, direct_cost, contribution, shared, global_cost,
            ) in sorted(
                buckets.items(),
                key=lambda item: (
                    item[0][0], tuple((name, str(value)) for name, value in item[0][1]),
                ),
            )
            for allocated_contribution in (contribution - shared,)
        )

    @staticmethod
    def _upstream_by_earning(rows):
        result = {}
        for row in rows:
            earning = dict(row.dimensions).get("earning")
            if earning is None or earning in result:
                raise ValueError("M10A9D earning-grain allocated contribution lineage is ambiguous")
            result[earning] = row
        return result
