"""Read-only economic association contracts for frozen M11 candidate buckets."""

from dataclasses import dataclass
from decimal import Decimal


ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION = "m11a5b-eligible-economic-candidate-v1"
ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS = (
    "read-only snapshot-safe association of frozen M11A4 evidence-eligible candidate identities "
    "with exact frozen M11A1 operating-profit values from the same traversal and snapshot; "
    "native currency/no FX; no monetary recomputation, comparison, ranking, recommendation, or action"
)


@dataclass(frozen=True)
class EligibleEconomicCandidateRow:
    currency: str
    dimensions: tuple[tuple[str, str | int | None], ...]
    operating_profit: Decimal
    evaluated_at: object
    policy_version: str
    policy_fingerprint: str
    source_operating_profit_semantics: str
    source_signal_semantics: str
    source_signal_contract_version: str
    source_evidence_semantics: str
    source_evidence_contract_version: str
    source_eligibility_semantics: str
    source_eligibility_contract_version: str
    source_candidate_set_semantics: str
    source_candidate_set_contract_version: str
    eligible_economic_candidate_semantics: str = ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
    eligible_economic_candidate_contract_version: str = ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION
