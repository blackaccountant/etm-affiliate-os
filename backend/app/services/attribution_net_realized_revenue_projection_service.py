"""Deterministic, read-only M10A8 net realized commission projection."""
from collections import defaultdict
from decimal import Decimal
from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest, NetRealizedRevenueProjectionRow
from app.repositories.attribution_net_realized_revenue_projection_repository import AttributionNetRealizedRevenueProjectionRepository
from app.repositories.attribution_realized_revenue_projection_repository import AttributionRealizedRevenueProjectionRepository

class AttributionNetRealizedRevenueProjectionService:
    def __init__(self, db):
        self.settled = AttributionRealizedRevenueProjectionRepository(db); self.adjustments = AttributionNetRealizedRevenueProjectionRepository(db)
    def project(self, request: NetRealizedRevenueProjectionRequest | None = None) -> tuple[NetRealizedRevenueProjectionRow, ...]:
        normalized = (request or NetRealizedRevenueProjectionRequest()).normalized()
        records = self.settled.settled_lineage(currency=normalized.currency)
        adjustment_totals = self.adjustments.adjustments_by_settled_lineage(records)
        buckets = defaultdict(lambda: Decimal("0"))
        for record in records:
            net = Decimal(str(record.commission_amount)) + Decimal(str(adjustment_totals.get(record.earning, 0)))
            if net < 0: raise ValueError("negative net realized commission violates adjustment authority")
            dimensions = tuple((name, getattr(record, name)) for name in normalized.dimensions)
            buckets[(record.currency, dimensions)] += net
        return tuple(NetRealizedRevenueProjectionRow(currency, amount, dimensions) for (currency, dimensions), amount in sorted(buckets.items(), key=lambda item: (item[0][0], tuple((name, str(value)) for name, value in item[0][1]))))
