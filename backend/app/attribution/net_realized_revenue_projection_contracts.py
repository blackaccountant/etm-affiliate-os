"""Read-only, adjustment-aware net realized commission projection contracts."""
from dataclasses import dataclass
from decimal import Decimal
from app.attribution.realized_revenue_projection_contracts import normalize_currency, normalize_dimensions

NET_REALIZED_REVENUE_PROJECTION_SEMANTICS = "net realized commission projection from settled authority and immutable financial adjustments"

@dataclass(frozen=True)
class NetRealizedRevenueProjectionRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None
    def normalized(self):
        return NetRealizedRevenueProjectionRequest(normalize_dimensions(self.dimensions), normalize_currency(self.currency))

@dataclass(frozen=True)
class NetRealizedRevenueProjectionRow:
    currency: str
    net_realized_commission: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    semantics: str = NET_REALIZED_REVENUE_PROJECTION_SEMANTICS
