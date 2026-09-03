"""Read-only settled-lineage evidence contracts for M11 consumers."""

from dataclasses import dataclass
from datetime import datetime

from app.optimization.operating_profit_signal_contracts import OperatingProfitSignalRequest


OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION = "m11a2-operating-profit-evidence-v1"
OPERATING_PROFIT_EVIDENCE_SEMANTICS = (
    "read-only settled-lineage measurement aligned to M11A1 operating-profit signal buckets; "
    "native-currency partitioned; raw settlement-link observation timestamps only; no confidence; "
    "no freshness classification; no eligibility; no ranking; no recommendation; no action; "
    "no financial interpretation"
)


@dataclass(frozen=True)
class OperatingProfitEvidenceRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "OperatingProfitEvidenceRequest":
        frozen = OperatingProfitSignalRequest(self.dimensions, self.currency).normalized()
        return OperatingProfitEvidenceRequest(frozen.dimensions, frozen.currency)


@dataclass(frozen=True)
class OperatingProfitEvidenceRow:
    currency: str
    dimensions: tuple[tuple[str, str | int | None], ...]
    settled_earning_count: int
    settled_conversion_count: int
    attribution_click_count: int
    settlement_link_count: int
    first_settlement_observed_at: datetime
    latest_settlement_observed_at: datetime
    source_signal_semantics: str
    source_signal_contract_version: str
    evidence_semantics: str = OPERATING_PROFIT_EVIDENCE_SEMANTICS
    evidence_contract_version: str = OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION
