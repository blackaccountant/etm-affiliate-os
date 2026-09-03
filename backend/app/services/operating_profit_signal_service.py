"""One-to-one M11 consumer mapping over frozen M10A9F operating-profit rows."""

from app.attribution.operating_profit_projection_contracts import (
    OperatingProfitProjectionRequest,
)
from app.optimization.operating_profit_signal_contracts import (
    OperatingProfitSignalRequest,
    OperatingProfitSignalRow,
)
from app.services.attribution_operating_profit_projection_service import (
    AttributionOperatingProfitProjectionService,
)


class OperatingProfitSignalService:
    """Expose M10A9F rows without additional SQL, arithmetic, or authority access."""

    def __init__(self, db):
        self._operating_profit = AttributionOperatingProfitProjectionService(db)

    def project(
        self, request: OperatingProfitSignalRequest | None = None,
    ) -> tuple[OperatingProfitSignalRow, ...]:
        normalized = (request or OperatingProfitSignalRequest()).normalized()
        upstream = self._operating_profit.project(
            OperatingProfitProjectionRequest(normalized.dimensions, normalized.currency),
        )
        return tuple(
            OperatingProfitSignalRow(
                currency=row.currency,
                net_realized_commission=row.net_realized_commission,
                directly_attributable_cost=row.directly_attributable_cost,
                contribution_profit=row.contribution_profit,
                allocated_shared_cost=row.allocated_shared_cost,
                allocated_contribution_profit=row.allocated_contribution_profit,
                allocated_global_cost=row.allocated_global_cost,
                operating_profit=row.operating_profit,
                dimensions=row.dimensions,
                source_semantics=row.semantics,
            )
            for row in upstream
        )
