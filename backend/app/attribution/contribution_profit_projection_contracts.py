"""Read-only, revenue-rooted direct contribution-profit projection contracts."""
from dataclasses import dataclass
from decimal import Decimal

from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest


CONTRIBUTION_PROFIT_PROJECTION_SEMANTICS = (
    "read-only revenue-rooted direct contribution-profit projection from frozen net realized "
    "commission and eligible immutable direct cost; shared/global excluded; no allocation; native currency/no FX; not period/accounting-final profit"
)


@dataclass(frozen=True)
class ContributionProfitProjectionRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "ContributionProfitProjectionRequest":
        frozen = NetRealizedRevenueProjectionRequest(self.dimensions, self.currency).normalized()
        return ContributionProfitProjectionRequest(frozen.dimensions, frozen.currency)


@dataclass(frozen=True)
class ContributionProfitProjectionRow:
    currency: str
    net_realized_commission: Decimal
    directly_attributable_cost: Decimal
    contribution_profit: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    semantics: str = CONTRIBUTION_PROFIT_PROJECTION_SEMANTICS
