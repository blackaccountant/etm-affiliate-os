"""Validated input contracts for the durable discovery ledger."""

from __future__ import annotations

import json
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class _StringEnum(str, Enum):
    """Persist enum values as portable strings rather than database enums."""


class DiscoveryInputType(_StringEnum):
    MARKET = "MARKET"
    NICHE = "NICHE"
    SEED = "SEED"
    URL = "URL"


class DiscoveryRunStatus(_StringEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CandidateDisposition(_StringEnum):
    DISCOVERED = "DISCOVERED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SELECTED = "SELECTED"


class VerificationStatus(_StringEnum):
    UNVERIFIED = "UNVERIFIED"
    PARTIAL = "PARTIAL"
    VERIFIED = "VERIFIED"
    STALE = "STALE"


class CommissionModel(_StringEnum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"
    RECURRING_PERCENT = "RECURRING_PERCENT"
    RECURRING_FIXED = "RECURRING_FIXED"
    CPA = "CPA"
    CPL = "CPL"
    REVENUE_SHARE = "REVENUE_SHARE"
    UNKNOWN = "UNKNOWN"


def _normalized_json(value: Any) -> Any:
    """Reject non-JSON values and normalize mapping key order deterministically."""
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


class DiscoveryRunCreate(BaseModel):
    input_type: DiscoveryInputType
    input_value: str
    input_data: dict[str, Any] | list[Any] | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)

    @field_validator("input_value")
    @classmethod
    def input_value_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("input_value is required")
        return value

    @field_validator("input_data")
    @classmethod
    def normalize_input_data(cls, value):
        return _normalized_json(value)


class DiscoveryCandidateCreate(BaseModel):
    source_adapter: str
    source_type: str
    source_url: str | None = None
    vendor_name: str | None = None
    canonical_domain: str
    offer_name: str | None = None
    program_name: str | None = None
    affiliate_network: str | None = None
    affiliate_url: str | None = None
    program_identity_key: str
    dedupe_key: str
    commission_model: CommissionModel = CommissionModel.UNKNOWN
    commission_percent: Decimal | None = Field(default=None, ge=0, le=100)
    commission_amount: Decimal | None = Field(default=None, ge=0)
    commission_currency: str | None = Field(default=None, max_length=3)
    recurring_period: str | None = None
    cookie_days: int | None = Field(default=None, ge=0)
    payout_threshold: Decimal | None = Field(default=None, ge=0)
    payout_currency: str | None = Field(default=None, max_length=3)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    disposition: CandidateDisposition = CandidateDisposition.DISCOVERED
    confidence: int | None = Field(default=None, ge=0, le=100)
    score: int | None = Field(default=None, ge=0, le=100)
    score_breakdown: dict[str, Any] | list[Any] | None = None
    score_reasons: list[Any] | None = None

    @field_validator("commission_currency", "payout_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not value:
            return None
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter code")
        return value

    @field_validator("score_breakdown", "score_reasons")
    @classmethod
    def normalize_json(cls, value):
        return _normalized_json(value)

    @model_validator(mode="after")
    def require_identity_values(self):
        if not self.source_adapter.strip() or not self.source_type.strip():
            raise ValueError("source_adapter and source_type are required")
        if not self.canonical_domain.strip():
            raise ValueError("canonical_domain is required")
        return self


class EvidenceObservationCreate(BaseModel):
    candidate_id: str
    claim_type: str
    observed_value: Any
    source_url: str | None = None
    source_type: str
    excerpt: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_hash: str | None = None
    extractor: str
    extractor_version: str
    confidence: int | None = Field(default=None, ge=0, le=100)

    @field_validator("observed_value")
    @classmethod
    def normalize_observed_value(cls, value):
        return _normalized_json(value)

    @model_validator(mode="after")
    def require_provenance_values(self):
        required = (self.candidate_id, self.claim_type, self.source_type, self.extractor, self.extractor_version)
        if not all(value and value.strip() for value in required):
            raise ValueError("candidate, claim, source, and extractor metadata are required")
        return self
