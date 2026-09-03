"""Read-only deterministic pairwise comparison contracts for M11A5B candidates."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
    canonical_bucket_identity,
)


ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION = (
    "m11a6-economic-candidate-pairwise-comparison-v1"
)
ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS = (
    "read-only deterministic pairwise comparison of two distinct frozen M11A5B eligible "
    "economic candidates from one projection snapshot; higher exact operating_profit is preferred; "
    "exact Decimal equality is a tie; native currency/no FX; no monetary arithmetic or derived "
    "metric; no ranking, no recommendation, and no action"
)


@dataclass(frozen=True)
class OperatingProfitComparisonPolicy:
    policy_version: str

    def normalized(self):
        if type(self.policy_version) is not str or not self.policy_version.strip():
            raise ValueError("comparison policy version must be a nonblank string")
        return self


class EconomicCandidatePairwiseRelation(str, Enum):
    LEFT_PREFERRED = "LEFT_PREFERRED"
    TIE = "TIE"
    RIGHT_PREFERRED = "RIGHT_PREFERRED"


def _normalize_dimensions(dimensions, names):
    if type(dimensions) is not tuple or len(dimensions) != len(names):
        raise ValueError("pair dimensions contradict the candidate request grain")
    normalized = []
    for pair, name in zip(dimensions, names, strict=True):
        if type(pair) is not tuple or len(pair) != 2 or pair[0] != name:
            raise ValueError("pair dimensions contradict the candidate request grain")
        value = pair[1]
        if type(value) not in (str, int) and value is not None:
            raise ValueError("unsupported pair dimension value")
        normalized.append(pair)
    return tuple(normalized)


@dataclass(frozen=True)
class EconomicCandidatePairwiseComparisonRequest:
    candidate_request: EligibleOperatingProfitCandidateSetRequest
    left_dimensions: tuple[tuple[str, str | int | None], ...]
    right_dimensions: tuple[tuple[str, str | int | None], ...]
    comparison_policy: OperatingProfitComparisonPolicy

    def normalized(self):
        if self.candidate_request is None:
            raise ValueError("candidate request is required")
        normalized_candidate_request = self.candidate_request.normalized()
        if not isinstance(self.comparison_policy, OperatingProfitComparisonPolicy):
            raise ValueError("comparison policy is required")
        policy = self.comparison_policy.normalized()
        left = _normalize_dimensions(self.left_dimensions, normalized_candidate_request.dimensions)
        right = _normalize_dimensions(self.right_dimensions, normalized_candidate_request.dimensions)
        if canonical_bucket_identity(normalized_candidate_request.currency, left) == canonical_bucket_identity(
            normalized_candidate_request.currency, right,
        ):
            raise ValueError("pairwise self-comparison is invalid")
        return EconomicCandidatePairwiseComparisonRequest(
            normalized_candidate_request, left, right, policy,
        )


@dataclass(frozen=True)
class EconomicCandidatePairwiseComparisonRow:
    currency: str
    left_dimensions: tuple[tuple[str, str | int | None], ...]
    left_operating_profit: Decimal
    right_dimensions: tuple[tuple[str, str | int | None], ...]
    right_operating_profit: Decimal
    relation: EconomicCandidatePairwiseRelation
    evaluated_at: object
    eligibility_policy_version: str
    eligibility_policy_fingerprint: str
    comparison_policy_version: str
    source_economic_candidate_semantics: str
    source_economic_candidate_contract_version: str
    pairwise_comparison_semantics: str = ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS
    pairwise_comparison_contract_version: str = ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION
