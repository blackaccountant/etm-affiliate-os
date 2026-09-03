"""Read-only M11A4 eligible operating-profit candidate-set contracts."""

from dataclasses import dataclass

from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OperatingProfitEvidenceEligibilityPolicy,
    OperatingProfitEvidenceEligibilityRequest,
)


ELIGIBLE_OPERATING_PROFIT_CANDIDATE_SET_CONTRACT_VERSION = "m11a4-eligible-operating-profit-candidate-set-v1"
ELIGIBLE_OPERATING_PROFIT_CANDIDATE_SET_SEMANTICS = (
    "read-only deterministic canonical set of M11A3 evidence-eligible operating-profit "
    "bucket identities; native-currency partitioned; no money, comparison, ranking, "
    "recommendation, or action"
)


def canonical_bucket_identity(currency: str, dimensions: tuple[tuple[str, str | int | None], ...]) -> tuple:
    def value_key(value):
        if value is None:
            return ("none", "")
        if type(value) is int:
            return ("int", str(value))
        if type(value) is str:
            return ("str", value)
        raise ValueError("unsupported candidate dimension value")
    return currency, tuple((name, *value_key(value)) for name, value in dimensions)


@dataclass(frozen=True)
class EligibleOperatingProfitCandidateSetRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None
    eligibility_policy: OperatingProfitEvidenceEligibilityPolicy | None = None
    evaluated_at: object | None = None

    def normalized(self):
        upstream = OperatingProfitEvidenceEligibilityRequest(
            self.dimensions, self.currency, self.eligibility_policy, self.evaluated_at,
        ).normalized()
        if upstream.currency is None:
            raise ValueError("M11A4 requires an explicit native currency")
        return EligibleOperatingProfitCandidateSetRequest(
            upstream.dimensions, upstream.currency, upstream.policy, upstream.evaluated_at,
        )


@dataclass(frozen=True)
class EligibleOperatingProfitCandidateRow:
    currency: str
    dimensions: tuple[tuple[str, str | int | None], ...]
    evaluated_at: object
    policy_version: str
    policy_fingerprint: str
    source_evidence_semantics: str
    source_evidence_contract_version: str
    source_eligibility_semantics: str
    source_eligibility_contract_version: str
    candidate_set_semantics: str = ELIGIBLE_OPERATING_PROFIT_CANDIDATE_SET_SEMANTICS
    candidate_set_contract_version: str = ELIGIBLE_OPERATING_PROFIT_CANDIDATE_SET_CONTRACT_VERSION
