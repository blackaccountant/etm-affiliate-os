"""Strict read contracts for UIF5D audience intelligence visibility."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AudienceProfileVisibilityResponse(_Response):
    id: str
    subject_id: str
    profile_ruleset_version: str
    source_fingerprint: str
    derived_at: datetime
    effective_as_of: datetime
    last_signal_observed_at: datetime | None
    summary_json: Any


class AudienceSignalVisibilityResponse(_Response):
    id: str
    subject_id: str | None
    signal_type: str
    topic_slug: str
    topic_label: str
    intent_stage: str | None
    strength: int
    confidence: int
    ruleset_version: str
    model_version: str | None
    observed_at: datetime
    derived_at: datetime
    expires_at: datetime | None
    supersedes_signal_id: str | None
    rationale: str | None


class AudienceQualificationVisibilityResponse(_Response):
    id: str
    profile_id: str
    scoring_ruleset_version: str
    context_type: str
    problem_strength: int
    interest_alignment: int
    research_intent: int
    comparison_intent: int
    evaluation_intent: int
    pricing_intent: int
    purchase_request_intent: int
    purchase_signal: int
    engagement: int
    business_need_fit: int
    intent_score: int
    qualification_score: int
    qualification_status: str
    derived_at: datetime


class AudienceSegmentVisibilityResponse(_Response):
    id: str
    segment_key: str
    name: str
    description: str | None
    created_at: datetime
    retired_at: datetime | None


class AudienceSegmentRevisionVisibilityResponse(_Response):
    id: str
    segment_id: str
    revision_number: int
    segment_ruleset_version: str
    definition_fingerprint: str
    definition_json: Any
    created_at: datetime


class AudienceSegmentMembershipVisibilityResponse(_Response):
    id: str
    segment_revision_id: str
    profile_id: str
    is_member: bool
    evaluated_at: datetime


class AudienceVisibilitySnapshotResponse(BaseModel):
    profiles: list[AudienceProfileVisibilityResponse]
    signals: list[AudienceSignalVisibilityResponse]
    qualifications: list[AudienceQualificationVisibilityResponse]
    segments: list[AudienceSegmentVisibilityResponse]
    segment_revisions: list[AudienceSegmentRevisionVisibilityResponse]
    memberships: list[AudienceSegmentMembershipVisibilityResponse]
