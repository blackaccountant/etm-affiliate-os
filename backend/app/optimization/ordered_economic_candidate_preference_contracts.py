"""Read-only ordered economic preference contracts for frozen M11 candidates."""

from dataclasses import dataclass
from decimal import Decimal

from app.optimization.economic_candidate_comparison_contracts import (
    OperatingProfitComparisonPolicy,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
)


ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION = (
    "m11a7-ordered-economic-candidate-preference-v1"
)
ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS = (
    "read-only deterministic ordered dense-tier view of the complete frozen M11A5B "
    "eligible-economic candidate partition from one frozen snapshot; ordering is determined "
    "exclusively by frozen M11A6 pairwise relation; exact M11A6 ties share a tier and canonical "
    "identity order within a tie is presentation only; exact native-currency operating_profit is "
    "retained; no FX, monetary recomputation, no score, no recommendation, no selection, no allocation, and no action"
)


@dataclass(frozen=True)
class OrderedEconomicCandidatePreferenceRequest:
    candidate_request: EligibleOperatingProfitCandidateSetRequest
    comparison_policy: OperatingProfitComparisonPolicy

    def normalized(self):
        if self.candidate_request is None:
            raise ValueError("candidate request is required")
        candidate_request = self.candidate_request.normalized()
        if not isinstance(self.comparison_policy, OperatingProfitComparisonPolicy):
            raise ValueError("comparison policy is required")
        return OrderedEconomicCandidatePreferenceRequest(
            candidate_request, self.comparison_policy.normalized(),
        )


@dataclass(frozen=True)
class OrderedEconomicCandidatePreferenceRow:
    currency: str
    dimensions: tuple[tuple[str, str | int | None], ...]
    operating_profit: Decimal
    preference_tier: int
    evaluated_at: object
    eligibility_policy_version: str
    eligibility_policy_fingerprint: str
    comparison_policy_version: str
    source_economic_candidate_semantics: str
    source_economic_candidate_contract_version: str
    source_pairwise_comparison_semantics: str
    source_pairwise_comparison_contract_version: str
    ordered_preference_semantics: str = ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS
    ordered_preference_contract_version: str = ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION
