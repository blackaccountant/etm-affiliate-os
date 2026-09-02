"""Immutable authority contracts for explicit shared-cost allocations."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SharedCostAllocationLineRequest:
    affiliate_earning_id: int
    amount: Decimal


@dataclass(frozen=True)
class RecordSharedCostAllocationRequest:
    affiliate_cost_event_id: str
    allocations: tuple[SharedCostAllocationLineRequest, ...]
    policy_version: str
    source_namespace: str
    source_event_key: str


@dataclass(frozen=True)
class SharedCostAllocationLineRecord:
    affiliate_earning_id: int
    amount: Decimal
    fingerprint: str


@dataclass(frozen=True)
class SharedCostAllocationRecord:
    id: str
    affiliate_cost_event_id: str
    allocated_amount: Decimal
    currency: str
    policy_version: str
    source_namespace: str
    source_event_digest: str
    fingerprint: str
    allocations: tuple[SharedCostAllocationLineRecord, ...]
