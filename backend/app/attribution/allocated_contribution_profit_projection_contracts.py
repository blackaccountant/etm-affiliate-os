"""Read-only projection contracts for contribution profit after explicit shared-cost allocation."""
from dataclasses import dataclass
from decimal import Decimal

from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest


ALLOCATED_CONTRIBUTION_PROFIT_PROJECTION_SEMANTICS = (
    "read-only revenue-rooted allocated contribution-profit projection from frozen M10A9B "
    "contribution profit and finalized M10A9C shared-cost allocation lines; native currency/no FX; "
    "global and unallocated costs excluded; no automatic allocation; not period/accounting-final profit, P&L, or ROI"
)


@dataclass(frozen=True)
class AllocatedContributionProfitProjectionRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "AllocatedContributionProfitProjectionRequest":
        frozen = ContributionProfitProjectionRequest(self.dimensions, self.currency).normalized()
        return AllocatedContributionProfitProjectionRequest(frozen.dimensions, frozen.currency)


@dataclass(frozen=True)
class AllocatedContributionProfitProjectionRow:
    currency: str
    net_realized_commission: Decimal
    directly_attributable_cost: Decimal
    contribution_profit: Decimal
    allocated_shared_cost: Decimal
    allocated_contribution_profit: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    semantics: str = ALLOCATED_CONTRIBUTION_PROFIT_PROJECTION_SEMANTICS
