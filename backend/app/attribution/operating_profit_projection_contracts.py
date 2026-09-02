"""Read-only operating-profit projection contracts after explicit global allocation."""

from dataclasses import dataclass
from decimal import Decimal

from app.attribution.allocated_contribution_profit_projection_contracts import (
    AllocatedContributionProfitProjectionRequest,
)


OPERATING_PROFIT_PROJECTION_SEMANTICS = (
    "read-only revenue-rooted operating-profit projection from frozen M10A9D allocated "
    "contribution profit and finalized M10A9E global-cost allocation lines; native currency/no FX; "
    "no automatic allocation; not period/accounting-final profit, P&L, or ROI"
)


@dataclass(frozen=True)
class OperatingProfitProjectionRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "OperatingProfitProjectionRequest":
        frozen = AllocatedContributionProfitProjectionRequest(
            self.dimensions, self.currency,
        ).normalized()
        return OperatingProfitProjectionRequest(frozen.dimensions, frozen.currency)


@dataclass(frozen=True)
class OperatingProfitProjectionRow:
    currency: str
    net_realized_commission: Decimal
    directly_attributable_cost: Decimal
    contribution_profit: Decimal
    allocated_shared_cost: Decimal
    allocated_contribution_profit: Decimal
    allocated_global_cost: Decimal
    operating_profit: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    semantics: str = OPERATING_PROFIT_PROJECTION_SEMANTICS
