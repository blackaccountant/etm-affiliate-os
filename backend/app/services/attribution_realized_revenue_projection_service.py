"""Deterministic, read-only M10A6 settled commission projection service."""

from collections import defaultdict
from decimal import Decimal

from app.attribution.realized_revenue_projection_contracts import (
    RealizedRevenueProjectionRequest,
    SettledCommissionProjectionRow,
)
from app.repositories.attribution_realized_revenue_projection_repository import (
    AttributionRealizedRevenueProjectionRepository,
)


class AttributionRealizedRevenueProjectionService:
    def __init__(self, db):
        self.db = db
        self.projection = AttributionRealizedRevenueProjectionRepository(db)

    def project(self, request: RealizedRevenueProjectionRequest | None = None) -> tuple[SettledCommissionProjectionRow, ...]:
        normalized = (request or RealizedRevenueProjectionRequest()).normalized()
        buckets: dict[tuple[object, ...], Decimal] = defaultdict(lambda: Decimal("0"))
        for record in self.projection.settled_lineage(currency=normalized.currency):
            dimensions = tuple((name, getattr(record, name)) for name in normalized.dimensions)
            key = (record.currency, dimensions)
            buckets[key] += Decimal(str(record.commission_amount))
        return tuple(
            SettledCommissionProjectionRow(currency=currency, commission_amount=amount, dimensions=dimensions)
            for (currency, dimensions), amount in sorted(
                buckets.items(), key=lambda item: (item[0][0], tuple((name, str(value)) for name, value in item[0][1])),
            )
        )
