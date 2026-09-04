"""Strict read contracts for UIF5E attribution lineage visibility."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AttributionPublicationVisibilityResponse(_Response):
    id: str
    legacy_publishing_queue_id: int | None
    distribution_run_id: str | None
    created_at: datetime


class AttributionContextVisibilityResponse(_Response):
    id: str
    affiliate_program_id: int
    attribution_publication_id: str
    created_at: datetime


class AttributionClickVisibilityResponse(_Response):
    id: str
    attribution_context_id: str
    affiliate_link_id: int
    source_namespace: str
    occurred_at: datetime
    recorded_at: datetime


class AttributionFactVisibilityResponse(_Response):
    id: str
    fact_kind: str
    source_namespace: str
    attribution_publication_id: str | None
    attribution_context_id: str | None
    attribution_click_id: str | None
    affiliate_link_id: int | None
    affiliate_conversion_id: int | None
    supersedes_fact_id: str | None
    occurred_at: datetime
    recorded_at: datetime


class AttributionEarningLinkVisibilityResponse(_Response):
    id: str
    attribution_fact_id: str
    affiliate_conversion_id: int
    affiliate_earning_id: int
    source_namespace: str
    observed_at: datetime
    recorded_at: datetime


class AttributionPayoutSettlementVisibilityResponse(_Response):
    id: str
    attribution_earning_link_id: str
    affiliate_earning_id: int
    affiliate_payout_id: int
    affiliate_payout_attempt_id: int
    source_namespace: str
    observed_at: datetime
    recorded_at: datetime


class AttributionLineageSnapshotResponse(BaseModel):
    publications: list[AttributionPublicationVisibilityResponse]
    contexts: list[AttributionContextVisibilityResponse]
    clicks: list[AttributionClickVisibilityResponse]
    facts: list[AttributionFactVisibilityResponse]
    earning_links: list[AttributionEarningLinkVisibilityResponse]
    settlement_links: list[AttributionPayoutSettlementVisibilityResponse]
