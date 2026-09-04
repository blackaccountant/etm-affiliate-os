"""Read-only recommendation proposal contracts over frozen M11A7 preferences."""
from dataclasses import dataclass
from decimal import Decimal
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest

ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION = "m11a8-economic-recommendation-proposal-v1"
ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS = (
    "read-only deterministic proposal from one frozen M11A7 ordered-preference projection; "
    "recommends all and only preference_tier == 1 rows; exact Tier-1 ties are all retained in "
    "inherited presentation order; exact native-currency operating_profit retained; no FX, monetary "
    "recomputation, no score, no arbitrary winner, no approval, no allocation, no experiment, no execution, and no action"
)

@dataclass(frozen=True)
class EconomicRecommendationPolicy:
    policy_version: str
    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("recommendation policy version must be a nonblank string")
        return self

@dataclass(frozen=True)
class EconomicRecommendationProposalRequest:
    preference_request: OrderedEconomicCandidatePreferenceRequest
    recommendation_policy: EconomicRecommendationPolicy
    def normalized(self):
        if self.preference_request is None:
            raise ValueError("preference request is required")
        if not isinstance(self.recommendation_policy, EconomicRecommendationPolicy):
            raise ValueError("recommendation policy is required")
        return EconomicRecommendationProposalRequest(self.preference_request.normalized(), self.recommendation_policy.normalized())

@dataclass(frozen=True)
class EconomicRecommendationProposalRow:
    currency: str
    dimensions: tuple[tuple[str, str | int | None], ...]
    operating_profit: Decimal
    preference_tier: int
    evaluated_at: object
    eligibility_policy_version: str
    eligibility_policy_fingerprint: str
    comparison_policy_version: str
    recommendation_policy_version: str
    source_ordered_preference_semantics: str
    source_ordered_preference_contract_version: str
    recommendation_proposal_semantics: str = ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
    recommendation_proposal_contract_version: str = ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
