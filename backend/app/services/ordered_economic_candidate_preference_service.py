"""Order frozen M11A5B economics only through the frozen M11A6 relation authority."""

from decimal import Decimal

from app.optimization.economic_candidate_comparison_contracts import (
    ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION,
    ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS,
    EconomicCandidatePairwiseComparisonRequest,
    EconomicCandidatePairwiseComparisonRow,
    EconomicCandidatePairwiseRelation,
)
from app.optimization.eligible_economic_candidate_contracts import (
    ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION,
    ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import canonical_bucket_identity
from app.optimization.ordered_economic_candidate_preference_contracts import (
    OrderedEconomicCandidatePreferenceRequest,
    OrderedEconomicCandidatePreferenceRow,
)
from app.services.economic_candidate_comparison_service import EconomicCandidateComparisonService
from app.services.eligible_economic_candidate_service import EligibleEconomicCandidateService


class _CapturedEligibleEconomicCandidateService:
    """Request-local, SQL-free adapter for repeated frozen M11A6 comparisons."""

    def __init__(self):
        self._request = None
        self._candidates = None

    def load(self, candidate_request, candidates):
        if self._request is not None:
            raise RuntimeError("M11A7 candidate capture is already active")
        self._request, self._candidates = candidate_request, candidates

    def clear(self):
        self._request, self._candidates = None, None

    def project(self, candidate_request):
        if self._request is None or self._candidates is None:
            raise RuntimeError("M11A7 candidate capture is absent")
        if candidate_request.normalized() != self._request:
            raise ValueError("M11A6 request contradicts the active M11A7 capture")
        return self._candidates


class OrderedEconomicCandidatePreferenceService:
    """One real M11A5B traversal plus cached M11A6 composition per request."""

    def __init__(self, db, *, economic_candidate_service=None):
        self._economic_candidates = (
            EligibleEconomicCandidateService(db)
            if economic_candidate_service is None
            else economic_candidate_service
        )
        self._captured_candidates = _CapturedEligibleEconomicCandidateService()
        self._pairwise = EconomicCandidateComparisonService(
            db, economic_candidate_service=self._captured_candidates,
        )

    @staticmethod
    def _validate_candidates(candidates, normalized):
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
                raise ValueError("M11A5B candidate contradicts the M11A7 request")
            for pair, name in zip(dimensions, normalized.candidate_request.dimensions, strict=True):
                if (
                    type(pair) is not tuple
                    or len(pair) != 2
                    or pair[0] != name
                    or (type(pair[1]) not in (str, int) and pair[1] is not None)
                ):
                    raise ValueError("M11A5B candidate contradicts the M11A7 request")
            identity = canonical_bucket_identity(candidate.currency, dimensions)
            if identity in index:
                raise ValueError("duplicate M11A5B candidate identity")
            index[identity] = candidate
        return index

    @staticmethod
    def _inverse(relation):
        if relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED:
            return EconomicCandidatePairwiseRelation.RIGHT_PREFERRED
        if relation is EconomicCandidatePairwiseRelation.RIGHT_PREFERRED:
            return EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        if relation is EconomicCandidatePairwiseRelation.TIE:
            return relation
        raise ValueError("M11A6 relation is invalid")

    @staticmethod
    def _validate_pairwise(result, left, right, normalized):
        fingerprint = normalized.candidate_request.eligibility_policy.fingerprint()
        if (
            type(result) is not EconomicCandidatePairwiseComparisonRow
            or result.currency != normalized.candidate_request.currency
            or result.left_dimensions != left.dimensions
            or result.right_dimensions != right.dimensions
            or result.left_operating_profit is not left.operating_profit
            or result.right_operating_profit is not right.operating_profit
            or result.evaluated_at != normalized.candidate_request.evaluated_at
            or result.eligibility_policy_version != normalized.candidate_request.eligibility_policy.policy_version
            or result.eligibility_policy_fingerprint != fingerprint
            or result.comparison_policy_version != normalized.comparison_policy.policy_version
            or result.source_economic_candidate_semantics != ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
            or result.source_economic_candidate_contract_version
            != ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION
            or result.pairwise_comparison_semantics != ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS
            or result.pairwise_comparison_contract_version
            != ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION
            or type(result.relation) is not EconomicCandidatePairwiseRelation
        ):
            raise ValueError("M11A6 pairwise result contradicts the M11A7 request")

    def _relation(self, first, second, normalized, cache):
        first_identity = canonical_bucket_identity(first.currency, first.dimensions)
        second_identity = canonical_bucket_identity(second.currency, second.dimensions)
        if first_identity == second_identity:
            raise ValueError("M11A7 cannot compare one identity to itself")
        left, right = (first, second) if first_identity < second_identity else (second, first)
        key = (canonical_bucket_identity(left.currency, left.dimensions), canonical_bucket_identity(right.currency, right.dimensions))
        relation = cache.get(key)
        if relation is None:
            result = self._pairwise.project(EconomicCandidatePairwiseComparisonRequest(
                normalized.candidate_request, left.dimensions, right.dimensions,
                normalized.comparison_policy,
            ))
            self._validate_pairwise(result, left, right, normalized)
            relation = result.relation
            cache[key] = relation
        return relation if first is left else self._inverse(relation)

    def _merge_sort(self, candidates, normalized, cache):
        ordered = list(candidates)
        width = 1
        while width < len(ordered):
            merged = []
            for start in range(0, len(ordered), width * 2):
                left, right = ordered[start:start + width], ordered[start + width:start + width * 2]
                left_index = right_index = 0
                while left_index < len(left) and right_index < len(right):
                    relation = self._relation(left[left_index], right[right_index], normalized, cache)
                    if relation is EconomicCandidatePairwiseRelation.RIGHT_PREFERRED:
                        merged.append(right[right_index]); right_index += 1
                    else:
                        merged.append(left[left_index]); left_index += 1
                merged.extend(left[left_index:]); merged.extend(right[right_index:])
            ordered, width = merged, width * 2
        return ordered

    @staticmethod
    def _row(candidate, tier, normalized):
        return OrderedEconomicCandidatePreferenceRow(
            candidate.currency, candidate.dimensions, candidate.operating_profit, tier,
            candidate.evaluated_at, candidate.policy_version, candidate.policy_fingerprint,
            normalized.comparison_policy.policy_version, ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS,
            ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION,
            ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS,
            ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION,
        )

    def project(self, request: OrderedEconomicCandidatePreferenceRequest):
        normalized = request.normalized()
        if self._captured_candidates._request is not None:
            raise RuntimeError("M11A7 candidate capture is already active")
        candidates = self._economic_candidates.project(normalized.candidate_request)
        if type(candidates) is not tuple:
            raise ValueError("M11A5B candidates must be a tuple")
        index = self._validate_candidates(candidates, normalized)
        self._captured_candidates.load(normalized.candidate_request, candidates)
        try:
            initial = [index[identity] for identity in sorted(index)]
            if not initial:
                return ()
            if len(initial) == 1:
                return (self._row(initial[0], 1, normalized),)
            cache = {}
            ordered = self._merge_sort(initial, normalized, cache)
            rows, tier, previous = [self._row(ordered[0], 1, normalized)], 1, ordered[0]
            for candidate in ordered[1:]:
                relation = self._relation(previous, candidate, normalized, cache)
                if relation is EconomicCandidatePairwiseRelation.TIE:
                    pass
                elif relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED:
                    tier += 1
                else:
                    raise ValueError("M11A7 order contradicts M11A6 relation")
                rows.append(self._row(candidate, tier, normalized))
                previous = candidate
            return tuple(rows)
        finally:
            self._captured_candidates.clear()
