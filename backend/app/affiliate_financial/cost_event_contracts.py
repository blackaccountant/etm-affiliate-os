"""Contracts for immutable, native-currency affiliate operating costs."""
from dataclasses import dataclass
from decimal import Decimal

ALLOCATION_SCOPES = frozenset({"direct", "shared", "global"})


@dataclass(frozen=True)
class RecordAffiliateCostEventRequest:
    amount: Decimal
    currency: str
    cost_type: str
    allocation_scope: str
    source_namespace: str
    source_event_key: str
    product_id: int | None = None
    affiliate_program_id: int | None = None
    content_asset_id: int | None = None
    content_generation_run_id: str | None = None
    distribution_run_id: str | None = None
    affiliate_link_id: int | None = None
    affiliate_conversion_id: int | None = None
    affiliate_earning_id: int | None = None
    affiliate_payout_id: int | None = None
    affiliate_payout_attempt_id: int | None = None
    outreach_provider_dispatch_id: str | None = None


@dataclass(frozen=True)
class AffiliateCostEventRecord:
    id: str
    amount: Decimal
    currency: str
    cost_type: str
    allocation_scope: str
    source_namespace: str
    source_event_digest: str
    fingerprint: str
