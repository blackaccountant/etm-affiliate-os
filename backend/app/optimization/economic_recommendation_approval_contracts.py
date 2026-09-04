"""Read-only externally supplied approval contracts over frozen M11A8 proposals."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.optimization.economic_recommendation_proposal_contracts import (
    EconomicRecommendationProposalRequest,
)


ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION = (
    "m11a9-economic-recommendation-approval-v1"
)
ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS = (
    "read-only externally supplied approval over one frozen M11A8 recommendation proposal; "
    "no allocation, experiment, execution, action, or economic inference"
)


class EconomicRecommendationApprovalState(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class EconomicRecommendationApprovalPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("approval policy version must be nonblank")
        return self


@dataclass(frozen=True)
class EconomicRecommendationApprovalDecision:
    decision_state: EconomicRecommendationApprovalState
    approved_dimensions: tuple
    actor_reference: str
    decision_reference: str
    decided_at: datetime

    def normalized(self):
        if type(self.decision_state) is not EconomicRecommendationApprovalState:
            raise ValueError("invalid approval state")
        if type(self.approved_dimensions) is not tuple:
            raise ValueError("approved_dimensions must be a tuple")
        if any(
            type(value) is not str or not value.strip()
            for value in (self.actor_reference, self.decision_reference)
        ):
            raise ValueError("approval provenance must be nonblank")
        if (
            type(self.decided_at) is not datetime
            or self.decided_at.tzinfo is None
            or self.decided_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("decided_at must be timezone-aware UTC")
        if (
            self.decision_state is EconomicRecommendationApprovalState.APPROVED
            and not self.approved_dimensions
        ):
            raise ValueError("approval requires candidates")
        if (
            self.decision_state is not EconomicRecommendationApprovalState.APPROVED
            and self.approved_dimensions
        ):
            raise ValueError("non-approval cannot select candidates")
        return self


@dataclass(frozen=True)
class EconomicRecommendationApprovalRequest:
    proposal_request: EconomicRecommendationProposalRequest
    approval_decision: EconomicRecommendationApprovalDecision
    approval_policy: EconomicRecommendationApprovalPolicy

    def normalized(self):
        if not isinstance(self.proposal_request, EconomicRecommendationProposalRequest):
            raise ValueError("proposal request is required")
        if not isinstance(self.approval_decision, EconomicRecommendationApprovalDecision):
            raise ValueError("approval decision is required")
        if not isinstance(self.approval_policy, EconomicRecommendationApprovalPolicy):
            raise ValueError("approval policy is required")
        return EconomicRecommendationApprovalRequest(
            self.proposal_request.normalized(),
            self.approval_decision.normalized(),
            self.approval_policy.normalized(),
        )


@dataclass(frozen=True)
class EconomicRecommendationApprovalOutcome:
    currency: str
    decision_state: EconomicRecommendationApprovalState
    approved_rows: tuple
    evaluated_at: datetime
    actor_reference: str
    decision_reference: str
    decided_at: datetime
    recommendation_policy_version: str
    approval_policy_version: str
    source_recommendation_semantics: str
    source_recommendation_contract_version: str
    approval_semantics: str = ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS
    approval_contract_version: str = ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
