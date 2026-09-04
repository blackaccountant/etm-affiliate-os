"""Strict transport contracts for UIF5F economic performance visibility."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class EconomicPerformanceRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    currency: str
    net_realized_commission: Decimal
    directly_attributable_cost: Decimal
    contribution_profit: Decimal
    allocated_shared_cost: Decimal
    allocated_contribution_profit: Decimal
    allocated_global_cost: Decimal
    operating_profit: Decimal
    semantics: str


class EconomicPerformanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[EconomicPerformanceRowResponse]
