"""Strict HTTP schemas for the UIF4A read-only experiment-design projection API."""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

from app.api.optimization_approval_schemas import (
    UIF3AApprovalDimensionRequest,
    UIF3AApprovalProjectionRequest,
)
from app.api.optimization_recommendation_schemas import (
    UIF2ARecommendationResponseRow,
)


class UIF4AExperimentDesignInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_reference: StrictStr
    approved_dimensions: list[UIF3AApprovalDimensionRequest]
    hypothesis: StrictStr
    control_definition: StrictStr
    treatment_definition: StrictStr
    success_measure: StrictStr
    observation_window: timedelta
    design_reference: StrictStr
    designed_at: datetime

    @field_validator(
        "experiment_reference",
        "hypothesis",
        "control_definition",
        "treatment_definition",
        "success_measure",
        "design_reference",
    )
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("experiment design text fields must be nonblank")
        return value

    @field_validator("observation_window", mode="before")
    @classmethod
    def _duration_transport_is_explicit(cls, value):
        if not isinstance(value, str):
            raise ValueError("observation_window must be an ISO-8601 duration string")
        return value

    @field_validator("observation_window")
    @classmethod
    def _positive_window(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("observation_window must be positive")
        return value

    @field_validator("designed_at")
    @classmethod
    def _utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("designed_at must be timezone-aware UTC")
        return value


class UIF4AExperimentDesignPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: StrictStr

    @field_validator("policy_version")
    @classmethod
    def _nonblank_policy_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("experiment design policy version must be nonblank")
        return value


class UIF4AExperimentDesignProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_request: UIF3AApprovalProjectionRequest
    experiment_design_inputs: list[UIF4AExperimentDesignInputRequest]
    experiment_design_policy: UIF4AExperimentDesignPolicyRequest


class UIF4AExperimentDesignResponseRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_reference: str
    approved_recommendation_row: UIF2ARecommendationResponseRow
    hypothesis: str
    control_definition: str
    treatment_definition: str
    success_measure: str
    observation_window: timedelta
    actor_reference: str
    decision_reference: str
    decided_at: str
    design_reference: str
    designed_at: str
    recommendation_policy_version: str
    approval_policy_version: str
    experiment_design_policy_version: str
    source_approval_semantics: str
    source_approval_contract_version: str
    experiment_design_semantics: str
    experiment_design_contract_version: str


class UIF4AExperimentDesignProjectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_designs: list[UIF4AExperimentDesignResponseRow]
