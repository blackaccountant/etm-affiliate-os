"""Immutable authority contracts for explicit global-cost allocations."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class GlobalCostAllocationLineRequest:
    affiliate_earning_id: int
    amount: Decimal


@dataclass(frozen=True)
class RecordGlobalCostAllocationRequest:
    affiliate_cost_event_id: str
    allocations: tuple[GlobalCostAllocationLineRequest, ...]
    policy_version: str
    source_namespace: str
    source_event_key: str


@dataclass(frozen=True)
class GlobalCostAllocationLineRecord:
    affiliate_earning_id: int
    amount: Decimal
    fingerprint: str


@dataclass(frozen=True)
class GlobalCostAllocationRecord:
    id: str
    affiliate_cost_event_id: str
    allocated_amount: Decimal
    currency: str
    policy_version: str
    source_namespace: str
    source_event_digest: str
    fingerprint: str
    allocations: tuple[GlobalCostAllocationLineRecord, ...]
