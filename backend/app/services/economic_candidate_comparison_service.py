"""Compare two explicit M11A5B economic candidates without ranking or recomputation."""

from decimal import Decimal

from app.optimization.economic_candidate_comparison_contracts import (
    EconomicCandidatePairwiseComparisonRequest,
    EconomicCandidatePairwiseComparisonRow,
    EconomicCandidatePairwiseRelation,
)
from app.optimization.eligible_economic_candidate_contracts import (
    ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION,
    ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import canonical_bucket_identity
from app.services.eligible_economic_candidate_service import EligibleEconomicCandidateService


class EconomicCandidateComparisonService:
    """Read-only orientation-preserving comparison over one M11A5B projection."""

    def __init__(self, db, *, economic_candidate_service=None):
        self._economic_candidates = (
            EligibleEconomicCandidateService(db)
            if economic_candidate_service is None
            else economic_candidate_service
        )

    @staticmethod
    def _index_candidates(candidates, normalized):
        fingerprint = normalized.candidate_request.eligibility_policy.fingerprint()
        index = {}
        for candidate in candidates:
            dimensions = candidate.dimensions
            if (
                candidate.currency != normalized.candidate_request.currency
                or type(dimensions) is not tuple
                or len(dimensions) != len(normalized.candidate_request.dimensions)
                or candidate.evaluated_at != normalized.candidate_request.evaluated_at
                or candidate.policy_version != normalized.candidate_request.eligibility_policy.policy_version
                or candidate.policy_fingerprint != fingerprint
                or candidate.eligible_economic_candidate_semantics != ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
                or candidate.eligible_economic_candidate_contract_version
                != ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION
                or type(candidate.operating_profit) is not Decimal
            ):
                raise ValueError("M11A5B candidate contradicts the M11A6 request")
            for pair, name in zip(dimensions, normalized.candidate_request.dimensions, strict=True):
                if (
                    type(pair) is not tuple
                    or len(pair) != 2
                    or pair[0] != name
                    or (type(pair[1]) not in (str, int) and pair[1] is not None)
                ):
                    raise ValueError("M11A5B candidate contradicts the M11A6 request")
            identity = canonical_bucket_identity(candidate.currency, dimensions)
            if identity in index:
                raise ValueError("duplicate M11A5B candidate identity")
            index[identity] = candidate
        return index

    def project(self, request: EconomicCandidatePairwiseComparisonRequest):
        normalized = request.normalized()
        candidates = self._economic_candidates.project(normalized.candidate_request)
        index = self._index_candidates(candidates, normalized)
        currency = normalized.candidate_request.currency
        left = index.get(canonical_bucket_identity(currency, normalized.left_dimensions))
        if left is None:
            raise ValueError("requested left candidate is absent from M11A5B")
        right = index.get(canonical_bucket_identity(currency, normalized.right_dimensions))
        if right is None:
            raise ValueError("requested right candidate is absent from M11A5B")
        if left.operating_profit > right.operating_profit:
            relation = EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        elif left.operating_profit < right.operating_profit:
            relation = EconomicCandidatePairwiseRelation.RIGHT_PREFERRED
        else:
            relation = EconomicCandidatePairwiseRelation.TIE
        return EconomicCandidatePairwiseComparisonRow(
            currency=currency,
            left_dimensions=left.dimensions,
            left_operating_profit=left.operating_profit,
            right_dimensions=right.dimensions,
            right_operating_profit=right.operating_profit,
            relation=relation,
            evaluated_at=left.evaluated_at,
            eligibility_policy_version=left.policy_version,
            eligibility_policy_fingerprint=left.policy_fingerprint,
            comparison_policy_version=normalized.comparison_policy.policy_version,
            source_economic_candidate_semantics=left.eligible_economic_candidate_semantics,
            source_economic_candidate_contract_version=left.eligible_economic_candidate_contract_version,
        )
