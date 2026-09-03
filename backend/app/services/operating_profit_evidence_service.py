"""Measure settled-lineage evidence only after frozen M11A1 establishes the snapshot."""

from collections import defaultdict

from app.attribution.realized_revenue_projection_contracts import ALLOWED_DIMENSIONS
from app.optimization.operating_profit_evidence_contracts import (
    OperatingProfitEvidenceRequest,
    OperatingProfitEvidenceRow,
)
from app.optimization.operating_profit_signal_contracts import OperatingProfitSignalRequest
from app.repositories.attribution_realized_revenue_projection_repository import (
    AttributionRealizedRevenueProjectionRepository,
)
from app.repositories.operating_profit_evidence_repository import OperatingProfitEvidenceRepository
from app.services.operating_profit_signal_service import OperatingProfitSignalService


class OperatingProfitEvidenceService:
    """Expose non-financial settled-lineage measurements aligned to M11A1 buckets."""

    def __init__(self, db):
        self._signals = OperatingProfitSignalService(db)
        self._settled_lineage = AttributionRealizedRevenueProjectionRepository(db)
        self._observations = OperatingProfitEvidenceRepository(db)

    def project(
        self, request: OperatingProfitEvidenceRequest | None = None,
    ) -> tuple[OperatingProfitEvidenceRow, ...]:
        normalized = (request or OperatingProfitEvidenceRequest()).normalized()
        signals = self._signals.project(
            OperatingProfitSignalRequest(normalized.dimensions, normalized.currency),
        )
        signal_keys = {(row.currency, row.dimensions) for row in signals}
        lineage = self._settled_lineage.settled_lineage(currency=normalized.currency)
        observed = dict(self._observations.observed_at_by_settlement_link(
            record.settlement_link for record in lineage
        ))
        buckets = defaultdict(lambda: {"earnings": set(), "conversions": set(), "clicks": set(), "links": set(), "times": []})
        for record in lineage:
            dimensions = tuple((name, getattr(record, name)) for name in normalized.dimensions)
            key = (record.currency, dimensions)
            if key not in signal_keys:
                continue
            observed_at = observed.get(record.settlement_link)
            if observed_at is None:
                raise ValueError("settled lineage has no valid settlement-link observation timestamp")
            bucket = buckets[key]
            bucket["earnings"].add(record.earning)
            bucket["conversions"].add(record.conversion)
            if record.attribution_click is not None:
                bucket["clicks"].add(record.attribution_click)
            bucket["links"].add(record.settlement_link)
            bucket["times"].append(observed_at)
        rows = []
        for signal in signals:
            bucket = buckets.get((signal.currency, signal.dimensions))
            if bucket is None or not bucket["times"]:
                raise ValueError("M11A1 signal bucket lacks settled-lineage evidence")
            rows.append(OperatingProfitEvidenceRow(
                currency=signal.currency,
                dimensions=signal.dimensions,
                settled_earning_count=len(bucket["earnings"]),
                settled_conversion_count=len(bucket["conversions"]),
                attribution_click_count=len(bucket["clicks"]),
                settlement_link_count=len(bucket["links"]),
                first_settlement_observed_at=min(bucket["times"]),
                latest_settlement_observed_at=max(bucket["times"]),
                source_signal_semantics=signal.signal_semantics,
                source_signal_contract_version=signal.signal_contract_version,
            ))
        return tuple(rows)
