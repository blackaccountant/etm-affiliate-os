"""Resolve M10A8 evidence to immutable M11A15 observations without writes."""

from app.attribution.net_realized_revenue_projection_contracts import (
    NET_REALIZED_REVENUE_PROJECTION_SEMANTICS,
    NetRealizedRevenueProjectionRequest,
    NetRealizedRevenueProjectionRow,
)
from app.optimization.economic_recommendation_experiment_economic_evidence_contracts import (
    EconomicRecommendationExperimentEconomicEvidenceRequest,
    EconomicRecommendationExperimentEconomicEvidenceRow,
    NET_REALIZED_REVENUE_PROJECTION_TYPE,
    NO_EVIDENCE,
    RESOLVED,
)
from app.services.attribution_net_realized_revenue_projection_service import (
    AttributionNetRealizedRevenueProjectionService,
)


class EconomicRecommendationExperimentEconomicEvidenceService:
    def __init__(self, db, *, projection_service=None):
        self.db = db
        self._projection = (
            AttributionNetRealizedRevenueProjectionService(db)
            if projection_service is None else projection_service
        )

    @staticmethod
    def _row(observation, *, dimensions, amount, currency, classification):
        return EconomicRecommendationExperimentEconomicEvidenceRow(
            observation_fingerprint=observation.observation_fingerprint,
            experiment_reference=observation.experiment_reference,
            activation_reference=observation.activation_reference,
            distribution_run_id=observation.distribution_run_id,
            mission_id=observation.mission_id,
            execution_id=observation.execution_id,
            mission_status=observation.mission_status,
            execution_status=observation.execution_status,
            distribution_run_status=observation.distribution_run_status,
            terminal_classification=observation.terminal_classification,
            success_failure_classification=observation.success_failure_classification,
            source_projection_type=NET_REALIZED_REVENUE_PROJECTION_TYPE,
            source_projection_semantics=NET_REALIZED_REVENUE_PROJECTION_SEMANTICS,
            source_dimensions=dimensions,
            net_realized_commission=amount,
            currency=currency,
            evidence_resolution_classification=classification,
        )

    @staticmethod
    def _sources_by_distribution_run(rows):
        result = {}
        for row in rows:
            if type(row) is not NetRealizedRevenueProjectionRow:
                raise ValueError("M10A8 projection row type is invalid")
            if row.semantics != NET_REALIZED_REVENUE_PROJECTION_SEMANTICS:
                raise ValueError("M10A8 projection semantics is invalid")
            dimensions = tuple(row.dimensions)
            if len(dimensions) != 1 or dimensions[0][0] != "distribution_run":
                raise ValueError("M10A8 projection dimensions are invalid")
            result.setdefault(dimensions[0][1], []).append(row)
        return result

    def resolve(self, request: EconomicRecommendationExperimentEconomicEvidenceRequest):
        normalized = request.normalized()
        projection_rows = self._projection.project(
            NetRealizedRevenueProjectionRequest(dimensions=("distribution_run",))
        )
        sources = self._sources_by_distribution_run(projection_rows)
        resolved = []
        for observation in normalized.observations:
            matching = sources.get(observation.distribution_run_id, ())
            if not matching:
                resolved.append(self._row(
                    observation,
                    dimensions=(("distribution_run", observation.distribution_run_id),),
                    amount=None,
                    currency=None,
                    classification=NO_EVIDENCE,
                ))
                continue
            for source in matching:
                resolved.append(self._row(
                    observation,
                    dimensions=tuple(source.dimensions),
                    amount=source.net_realized_commission,
                    currency=source.currency,
                    classification=RESOLVED,
                ))
        return tuple(resolved)
