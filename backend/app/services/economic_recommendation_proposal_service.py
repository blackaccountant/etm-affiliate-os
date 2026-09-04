"""Propose every Tier-1 frozen M11A7 preference without re-ranking it."""
from decimal import Decimal
from app.optimization.economic_candidate_comparison_contracts import ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION, ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS
from app.optimization.eligible_economic_candidate_contracts import ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION, ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
from app.optimization.eligible_operating_profit_candidate_set_contracts import canonical_bucket_identity
from app.optimization.ordered_economic_candidate_preference_contracts import ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION, ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS, OrderedEconomicCandidatePreferenceRow
from app.optimization.economic_recommendation_proposal_contracts import EconomicRecommendationProposalRequest, EconomicRecommendationProposalRow
from app.services.ordered_economic_candidate_preference_service import OrderedEconomicCandidatePreferenceService

class EconomicRecommendationProposalService:
    def __init__(self, db, *, ordered_preference_service=None):
        self._ordered_preferences = OrderedEconomicCandidatePreferenceService(db) if ordered_preference_service is None else ordered_preference_service

    @staticmethod
    def _validate(rows, normalized):
        request, fingerprint, identities, previous = normalized.preference_request, normalized.preference_request.candidate_request.eligibility_policy.fingerprint(), set(), None
        for row in rows:
            dimensions = row.dimensions
            if (type(row) is not OrderedEconomicCandidatePreferenceRow or row.currency != request.candidate_request.currency or type(dimensions) is not tuple or len(dimensions) != len(request.candidate_request.dimensions) or row.evaluated_at != request.candidate_request.evaluated_at or row.eligibility_policy_version != request.candidate_request.eligibility_policy.policy_version or row.eligibility_policy_fingerprint != fingerprint or row.comparison_policy_version != request.comparison_policy.policy_version or row.source_economic_candidate_semantics != ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS or row.source_economic_candidate_contract_version != ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION or row.source_pairwise_comparison_semantics != ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS or row.source_pairwise_comparison_contract_version != ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION or row.ordered_preference_semantics != ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS or row.ordered_preference_contract_version != ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION or type(row.operating_profit) is not Decimal or type(row.preference_tier) is not int or row.preference_tier <= 0):
                raise ValueError("M11A7 row contradicts the M11A8 request")
            for pair, name in zip(dimensions, request.candidate_request.dimensions, strict=True):
                if type(pair) is not tuple or len(pair) != 2 or pair[0] != name or (type(pair[1]) not in (str, int) and pair[1] is not None):
                    raise ValueError("M11A7 row contradicts the M11A8 request")
            identity = canonical_bucket_identity(row.currency, dimensions)
            if identity in identities: raise ValueError("duplicate M11A7 preference identity")
            if previous is None:
                if row.preference_tier != 1: raise ValueError("M11A7 preference tuple must start at tier 1")
            elif row.preference_tier not in (previous.preference_tier, previous.preference_tier + 1):
                raise ValueError("M11A7 preference tiers are not dense")
            elif row.preference_tier == previous.preference_tier and canonical_bucket_identity(previous.currency, previous.dimensions) >= identity:
                raise ValueError("M11A7 same-tier presentation order is invalid")
            identities.add(identity); previous = row

    def project(self, request: EconomicRecommendationProposalRequest):
        normalized = request.normalized(); rows = self._ordered_preferences.project(normalized.preference_request)
        if type(rows) is not tuple: raise ValueError("M11A7 preferences must be a tuple")
        self._validate(rows, normalized)
        return tuple(EconomicRecommendationProposalRow(row.currency, row.dimensions, row.operating_profit, row.preference_tier, row.evaluated_at, row.eligibility_policy_version, row.eligibility_policy_fingerprint, row.comparison_policy_version, normalized.recommendation_policy.policy_version, ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS, ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION) for row in rows if row.preference_tier == 1)
