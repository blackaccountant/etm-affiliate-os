"""HTTP transport over frozen M11A9 external recommendation approval projection."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.optimization_approval_schemas import (
    UIF3AApprovalOutcomeResponse,
    UIF3AApprovalProjectionRequest,
)
from app.api.optimization_recommendation_schemas import (
    UIF2ADimensionResponse,
    UIF2ARecommendationResponseRow,
)
from app.dependencies import get_db
from app.optimization.economic_candidate_comparison_contracts import (
    OperatingProfitComparisonPolicy,
)
from app.optimization.economic_recommendation_approval_contracts import (
    EconomicRecommendationApprovalDecision,
    EconomicRecommendationApprovalOutcome,
    EconomicRecommendationApprovalPolicy,
    EconomicRecommendationApprovalRequest,
    EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_proposal_contracts import (
    EconomicRecommendationPolicy,
    EconomicRecommendationProposalRequest,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
)
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OperatingProfitEvidenceEligibilityPolicy,
)
from app.optimization.ordered_economic_candidate_preference_contracts import (
    OrderedEconomicCandidatePreferenceRequest,
)
from app.services.economic_recommendation_approval_service import (
    EconomicRecommendationApprovalService,
)


router = APIRouter(
    prefix="/optimization/approvals",
    tags=["Optimization Approvals"],
)


def _proposal_domain_request(request) -> EconomicRecommendationProposalRequest:
    policy = request.eligibility_policy

    candidate_request = EligibleOperatingProfitCandidateSetRequest(
        dimensions=tuple(request.dimensions),
        currency=request.currency,
        eligibility_policy=OperatingProfitEvidenceEligibilityPolicy(
            policy_version=policy.policy_version,
            minimum_settled_earning_count=policy.minimum_settled_earning_count,
            minimum_settled_conversion_count=policy.minimum_settled_conversion_count,
            minimum_settlement_link_count=policy.minimum_settlement_link_count,
            minimum_attribution_click_count=policy.minimum_attribution_click_count,
            maximum_settlement_observation_age=(
                policy.maximum_settlement_observation_age
            ),
        ),
        evaluated_at=request.evaluated_at,
    )

    preference_request = OrderedEconomicCandidatePreferenceRequest(
        candidate_request=candidate_request,
        comparison_policy=OperatingProfitComparisonPolicy(
            request.comparison_policy_version
        ),
    )

    return EconomicRecommendationProposalRequest(
        preference_request=preference_request,
        recommendation_policy=EconomicRecommendationPolicy(
            request.recommendation_policy_version
        ),
    )


def _domain_request(
    request: UIF3AApprovalProjectionRequest,
) -> EconomicRecommendationApprovalRequest:
    decision = request.approval_decision
    approved_dimensions = tuple(
        tuple((item.name, item.value) for item in identity)
        for identity in decision.approved_dimensions
    )

    return EconomicRecommendationApprovalRequest(
        proposal_request=_proposal_domain_request(request.proposal_request),
        approval_decision=EconomicRecommendationApprovalDecision(
            decision_state=EconomicRecommendationApprovalState(
                decision.decision_state
            ),
            approved_dimensions=approved_dimensions,
            actor_reference=decision.actor_reference,
            decision_reference=decision.decision_reference,
            decided_at=decision.decided_at,
        ),
        approval_policy=EconomicRecommendationApprovalPolicy(
            policy_version=request.approval_policy.policy_version
        ),
    )


def _serialize_datetime(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("frozen approval timestamp is not a datetime")
    return value.isoformat()


def _serialize_recommendation_row(row) -> UIF2ARecommendationResponseRow:
    return UIF2ARecommendationResponseRow(
        currency=row.currency,
        dimensions=[
            UIF2ADimensionResponse(name=name, value=value)
            for name, value in row.dimensions
        ],
        operating_profit=str(row.operating_profit),
        preference_tier=row.preference_tier,
        evaluated_at=_serialize_datetime(row.evaluated_at),
        eligibility_policy_version=row.eligibility_policy_version,
        eligibility_policy_fingerprint=row.eligibility_policy_fingerprint,
        comparison_policy_version=row.comparison_policy_version,
        recommendation_policy_version=row.recommendation_policy_version,
        source_ordered_preference_semantics=(
            row.source_ordered_preference_semantics
        ),
        source_ordered_preference_contract_version=(
            row.source_ordered_preference_contract_version
        ),
        recommendation_proposal_semantics=row.recommendation_proposal_semantics,
        recommendation_proposal_contract_version=(
            row.recommendation_proposal_contract_version
        ),
    )


@router.post(
    "/decide",
    response_model=UIF3AApprovalOutcomeResponse,
    status_code=status.HTTP_200_OK,
)
def decide_recommendation_approval(
    request: UIF3AApprovalProjectionRequest,
    db: Session = Depends(get_db),
):
    try:
        domain_request = _domain_request(request)
        # Validate the complete frozen request before traversing the service graph.
        domain_request.normalized()
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="approval projection request violates frozen contract",
        ) from exc

    service = EconomicRecommendationApprovalService(db)

    try:
        outcome = service.project(domain_request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approval projection rejected by frozen optimization contract",
        ) from exc

    if type(outcome) is not EconomicRecommendationApprovalOutcome:
        raise RuntimeError("frozen M11A9 approval service returned invalid type")

    return UIF3AApprovalOutcomeResponse(
        currency=outcome.currency,
        decision_state=outcome.decision_state.value,
        approved_rows=[
            _serialize_recommendation_row(row)
            for row in outcome.approved_rows
        ],
        evaluated_at=_serialize_datetime(outcome.evaluated_at),
        actor_reference=outcome.actor_reference,
        decision_reference=outcome.decision_reference,
        decided_at=_serialize_datetime(outcome.decided_at),
        recommendation_policy_version=outcome.recommendation_policy_version,
        approval_policy_version=outcome.approval_policy_version,
        source_recommendation_semantics=outcome.source_recommendation_semantics,
        source_recommendation_contract_version=(
            outcome.source_recommendation_contract_version
        ),
        approval_semantics=outcome.approval_semantics,
        approval_contract_version=outcome.approval_contract_version,
    )
