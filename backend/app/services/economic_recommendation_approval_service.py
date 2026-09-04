"""Apply explicit external approval to one frozen M11A8 recommendation proposal."""

from decimal import Decimal

from app.optimization.economic_recommendation_approval_contracts import (
    EconomicRecommendationApprovalOutcome,
    EconomicRecommendationApprovalRequest,
)
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
    EconomicRecommendationProposalRow,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    canonical_bucket_identity,
)
from app.services.economic_recommendation_proposal_service import (
    EconomicRecommendationProposalService,
)


class EconomicRecommendationApprovalService:
    def __init__(self, db, *, recommendation_proposal_service=None):
        self._recommendations = (
            EconomicRecommendationProposalService(db)
            if recommendation_proposal_service is None
            else recommendation_proposal_service
        )

    @staticmethod
    def _validate_dimensions(dimensions, requested_names):
        if type(dimensions) is not tuple or len(dimensions) != len(requested_names):
            raise ValueError("approval dimensions contradict the requested grain")
        for pair, name in zip(dimensions, requested_names, strict=True):
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or pair[0] != name
                or (type(pair[1]) not in (str, int) and pair[1] is not None)
            ):
                raise ValueError("approval dimensions contradict the requested grain")

    @classmethod
    def _validate_source(cls, rows, normalized):
        proposal_request = normalized.proposal_request
        preference_request = proposal_request.preference_request
        candidate_request = preference_request.candidate_request
        requested_names = candidate_request.dimensions
        expected_fingerprint = candidate_request.eligibility_policy.fingerprint()
        identities = []
        previous_identity = None

        if type(rows) is not tuple:
            raise ValueError("M11A8 recommendations must be tuple")

        for row in rows:
            if (
                type(row) is not EconomicRecommendationProposalRow
                or row.currency != candidate_request.currency
                or type(row.operating_profit) is not Decimal
                or type(row.preference_tier) is not int
                or type(row.preference_tier) is bool
                or row.preference_tier != 1
                or row.evaluated_at != candidate_request.evaluated_at
                or row.eligibility_policy_version
                != candidate_request.eligibility_policy.policy_version
                or row.eligibility_policy_fingerprint != expected_fingerprint
                or row.comparison_policy_version
                != preference_request.comparison_policy.policy_version
                or row.recommendation_policy_version
                != proposal_request.recommendation_policy.policy_version
                or row.recommendation_proposal_semantics
                != ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
                or row.recommendation_proposal_contract_version
                != ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
            ):
                raise ValueError("M11A8 row contradicts the M11A9 request")

            cls._validate_dimensions(row.dimensions, requested_names)
            identity = canonical_bucket_identity(row.currency, row.dimensions)
            if identity in identities:
                raise ValueError("duplicate M11A8 identity")
            if previous_identity is not None and previous_identity >= identity:
                raise ValueError("M11A8 Tier-1 presentation order is invalid")
            identities.append(identity)
            previous_identity = identity

        return identities

    @classmethod
    def _select_rows(cls, rows, identities, normalized):
        candidate_request = normalized.proposal_request.preference_request.candidate_request
        requested_names = candidate_request.dimensions
        index_by_identity = {
            identity: index for index, identity in enumerate(identities)
        }
        selected = []
        seen = set()
        previous_index = -1

        for dimensions in normalized.approval_decision.approved_dimensions:
            cls._validate_dimensions(dimensions, requested_names)
            identity = canonical_bucket_identity(candidate_request.currency, dimensions)
            if identity in seen:
                raise ValueError("duplicate approved identity")
            seen.add(identity)
            index = index_by_identity.get(identity)
            if index is None or index <= previous_index:
                raise ValueError("approval selection contradicts M11A8 order")
            selected.append(rows[index])
            previous_index = index

        return tuple(selected)

    def project(self, request: EconomicRecommendationApprovalRequest):
        normalized = request.normalized()
        rows = self._recommendations.project(normalized.proposal_request)
        identities = self._validate_source(rows, normalized)
        selected = self._select_rows(rows, identities, normalized)

        evaluated_at = (
            normalized.proposal_request.preference_request.candidate_request.evaluated_at
        )
        if normalized.approval_decision.decided_at < evaluated_at:
            raise ValueError("decision predates evaluation")

        return EconomicRecommendationApprovalOutcome(
            currency=normalized.proposal_request.preference_request.candidate_request.currency,
            decision_state=normalized.approval_decision.decision_state,
            approved_rows=selected,
            evaluated_at=evaluated_at,
            actor_reference=normalized.approval_decision.actor_reference,
            decision_reference=normalized.approval_decision.decision_reference,
            decided_at=normalized.approval_decision.decided_at,
            recommendation_policy_version=(
                normalized.proposal_request.recommendation_policy.policy_version
            ),
            approval_policy_version=normalized.approval_policy.policy_version,
            source_recommendation_semantics=ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
            source_recommendation_contract_version=(
                ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
            ),
        )
