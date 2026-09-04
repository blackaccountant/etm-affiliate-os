"""Read-only HTTP transport over frozen M11A8 recommendation projection."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.optimization.economic_candidate_comparison_contracts import (
    OperatingProfitComparisonPolicy,
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
from app.services.economic_recommendation_proposal_service import (
    EconomicRecommendationProposalService,
)

from app.api.optimization_recommendation_schemas import (
    UIF2ADimensionResponse,
    UIF2ARecommendationProjectionRequest,
    UIF2ARecommendationProjectionResponse,
    UIF2ARecommendationResponseRow,
)


router = APIRouter(
    prefix="/optimization/recommendations",
    tags=["Optimization Recommendations"],
)


def _domain_request(
    request: UIF2ARecommendationProjectionRequest,
) -> EconomicRecommendationProposalRequest:
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


def _serialize_datetime(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("frozen recommendation evaluated_at is not a datetime")
    return value.isoformat()


def _serialize_row(row) -> UIF2ARecommendationResponseRow:
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
    "/project",
    response_model=UIF2ARecommendationProjectionResponse,
    status_code=status.HTTP_200_OK,
)
def project_recommendations(
    request: UIF2ARecommendationProjectionRequest,
    db: Session = Depends(get_db),
):
    try:
        domain_request = _domain_request(request)
        # Validate the complete frozen request before traversing the service graph.
        domain_request.normalized()
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="recommendation projection request violates frozen contract",
        ) from exc

    service = EconomicRecommendationProposalService(db)

    try:
        rows = service.project(domain_request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="recommendation projection rejected by frozen optimization contract",
        ) from exc

    if type(rows) is not tuple:
        raise RuntimeError("frozen M11A8 recommendation service returned invalid type")

    return UIF2ARecommendationProjectionResponse(
        recommendations=[_serialize_row(row) for row in rows]
    )
