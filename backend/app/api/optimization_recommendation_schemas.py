"""Strict HTTP schemas for the read-only UIF2A recommendation projection API."""

from datetime import datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


DimensionValue = StrictStr | StrictInt | None


class UIF2AEligibilityPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: StrictStr
    minimum_settled_earning_count: Annotated[StrictInt, Field(ge=0)]
    minimum_settled_conversion_count: Annotated[StrictInt, Field(ge=0)]
    minimum_settlement_link_count: Annotated[StrictInt, Field(ge=0)]
    minimum_attribution_click_count: Annotated[StrictInt, Field(ge=0)] | None
    maximum_settlement_observation_age: timedelta | None

    @field_validator("policy_version")
    @classmethod
    def _nonblank_policy_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_version must be nonblank")
        return value

    @field_validator("maximum_settlement_observation_age")
    @classmethod
    def _nonnegative_age(cls, value: timedelta | None) -> timedelta | None:
        if value is not None and value < timedelta(0):
            raise ValueError("maximum_settlement_observation_age must be nonnegative")
        return value


class UIF2ARecommendationProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[StrictStr]
    currency: StrictStr
    evaluated_at: datetime
    eligibility_policy: UIF2AEligibilityPolicyRequest
    comparison_policy_version: StrictStr
    recommendation_policy_version: StrictStr

    @field_validator("dimensions")
    @classmethod
    def _dimensions_are_nonblank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("dimensions must contain nonblank names")
        return value

    @field_validator(
        "currency",
        "comparison_policy_version",
        "recommendation_policy_version",
    )
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must be nonblank")
        return value

    @field_validator("evaluated_at")
    @classmethod
    def _utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("evaluated_at must be timezone-aware UTC")
        return value


class UIF2ADimensionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: DimensionValue


class UIF2ARecommendationResponseRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    dimensions: list[UIF2ADimensionResponse]
    operating_profit: str
    preference_tier: int
    evaluated_at: str
    eligibility_policy_version: str
    eligibility_policy_fingerprint: str
    comparison_policy_version: str
    recommendation_policy_version: str
    source_ordered_preference_semantics: str
    source_ordered_preference_contract_version: str
    recommendation_proposal_semantics: str
    recommendation_proposal_contract_version: str


class UIF2ARecommendationProjectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[UIF2ARecommendationResponseRow]
