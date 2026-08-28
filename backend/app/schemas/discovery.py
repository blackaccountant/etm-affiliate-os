"""HTTP contracts for the durable discovery ledger."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.discovery.contracts import DiscoveryInputType


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DiscoveryRunCreateRequest(BaseModel):
    input_type: DiscoveryInputType
    input_value: str = Field(min_length=1)
    input_data: dict[str, Any] | list[Any] | None = None
    idempotency_key: str | None = Field(default=None, max_length=255)


class DiscoveryRunResponse(_Response):
    id: str
    input_type: str
    input_value: str
    input_data: Any | None
    status: str
    idempotency_key: str | None
    candidate_count: int
    verified_count: int
    selected_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class DiscoveryCandidateResponse(_Response):
    id: str
    run_id: str
    source_adapter: str
    source_type: str
    source_url: str | None
    vendor_name: str | None
    canonical_domain: str
    program_name: str | None
    affiliate_network: str | None
    affiliate_url: str | None
    program_identity_key: str
    dedupe_key: str
    commission_model: str
    commission_percent: Any | None
    commission_amount: Any | None
    commission_currency: str | None
    recurring_period: str | None
    cookie_days: int | None
    payout_threshold: Any | None
    payout_currency: str | None
    verification_status: str
    disposition: str
    confidence: int | None
    score: int | None
    score_breakdown: Any | None
    score_reasons: Any | None
    created_at: datetime
    updated_at: datetime


class EvidenceObservationResponse(_Response):
    id: str
    candidate_id: str
    claim_type: str
    observed_value: Any
    source_url: str | None
    source_type: str
    excerpt: str | None
    http_status: int | None
    content_hash: str | None
    extractor: str
    extractor_version: str
    confidence: int | None
    observed_at: datetime
    created_at: datetime


class DiscoveryExecuteRequest(BaseModel):
    top_n: int = Field(default=1, ge=1)
    minimum_score: int = Field(default=40, ge=0, le=100)
    minimum_evidence_confidence: int = Field(default=70, ge=0, le=100)


class DiscoveryExecutionResponse(BaseModel):
    run: DiscoveryRunResponse
    ranked_candidate_ids: list[str]
    selected_candidate_ids: list[str]


class DiscoveryRankingItemResponse(BaseModel):
    rank: int
    candidate: DiscoveryCandidateResponse
    evidence_count: int


class DiscoveryRankingResponse(BaseModel):
    items: list[DiscoveryRankingItemResponse]


class DiscoverySelectedResponse(BaseModel):
    candidates: list[DiscoveryCandidateResponse]
