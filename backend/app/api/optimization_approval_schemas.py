"""Strict HTTP schemas for the UIF3A external recommendation approval API."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator

from app.api.optimization_recommendation_schemas import (
    UIF2ARecommendationProjectionRequest,
    UIF2ARecommendationResponseRow,
)


DimensionValue = StrictStr | StrictInt | None
ApprovalStateValue = Literal["APPROVED", "REJECTED", "DEFERRED"]


class UIF3AApprovalDimensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    value: DimensionValue

    @field_validator("name")
    @classmethod
    def _nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("dimension name must be nonblank")
        return value


class UIF3AApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_state: ApprovalStateValue
    approved_dimensions: list[list[UIF3AApprovalDimensionRequest]]
    actor_reference: StrictStr
    decision_reference: StrictStr
    decided_at: datetime

    @field_validator("actor_reference", "decision_reference")
    @classmethod
    def _nonblank_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval provenance must be nonblank")
        return value

    @field_validator("decided_at")
    @classmethod
    def _utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("decided_at must be timezone-aware UTC")
        return value


class UIF3AApprovalPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: StrictStr

    @field_validator("policy_version")
    @classmethod
    def _nonblank_policy_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval policy version must be nonblank")
        return value


class UIF3AApprovalProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_request: UIF2ARecommendationProjectionRequest
    approval_decision: UIF3AApprovalDecisionRequest
    approval_policy: UIF3AApprovalPolicyRequest


class UIF3AApprovalOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str
    decision_state: ApprovalStateValue
    approved_rows: list[UIF2ARecommendationResponseRow]
    evaluated_at: str
    actor_reference: str
    decision_reference: str
    decided_at: str
    recommendation_policy_version: str
    approval_policy_version: str
    source_recommendation_semantics: str
    source_recommendation_contract_version: str
    approval_semantics: str
    approval_contract_version: str
