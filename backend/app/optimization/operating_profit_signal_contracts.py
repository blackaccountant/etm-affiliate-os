"""Stable read-only operating-profit signal contracts for M11 consumers."""

from dataclasses import dataclass
from decimal import Decimal

from app.attribution.operating_profit_projection_contracts import (
    OperatingProfitProjectionRequest,
)


OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION = "m11a1-operating-profit-signal-v1"
OPERATING_PROFIT_SIGNAL_SEMANTICS = (
    "read-only revenue-rooted consumer signal composed from frozen M10A9F operating-profit "
    "projection exactly once; native currency/no FX; not accounting-final P&L, ROI, or margin; "
    "not a recommendation, ranking, eligibility decision, or execution instruction; incapable "
    "of mutating attribution or financial authority"
)


@dataclass(frozen=True)
class OperatingProfitSignalRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "OperatingProfitSignalRequest":
        frozen = OperatingProfitProjectionRequest(self.dimensions, self.currency).normalized()
        return OperatingProfitSignalRequest(frozen.dimensions, frozen.currency)


@dataclass(frozen=True)
class OperatingProfitSignalRow:
    currency: str
    net_realized_commission: Decimal
    directly_attributable_cost: Decimal
    contribution_profit: Decimal
    allocated_shared_cost: Decimal
    allocated_contribution_profit: Decimal
    allocated_global_cost: Decimal
    operating_profit: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    source_semantics: str
    signal_semantics: str = OPERATING_PROFIT_SIGNAL_SEMANTICS
    signal_contract_version: str = OPERATING_PROFIT_SIGNAL_CONTRACT_VERSION
