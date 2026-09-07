"""Focused contracts for M11A16 read-only economic evidence resolution."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.attribution.net_realized_revenue_projection_contracts import (
    NET_REALIZED_REVENUE_PROJECTION_SEMANTICS,
    NetRealizedRevenueProjectionRow,
)
from app.models.economic_recommendation_experiment_observation import (
    EconomicRecommendationExperimentObservation,
)
from app.optimization.economic_recommendation_experiment_economic_evidence_contracts import (
    EconomicRecommendationExperimentEconomicEvidencePolicy,
    EconomicRecommendationExperimentEconomicEvidenceRequest,
    NO_EVIDENCE,
    RESOLVED,
    validate_observation,
)
from app.services.economic_recommendation_experiment_economic_evidence_service import (
    EconomicRecommendationExperimentEconomicEvidenceService,
)


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _observation(**changes):
    values = dict(
        id="observation-id", observation_fingerprint="a" * 64,
        experiment_reference="experiment", activation_reference="activation",
        distribution_run_id="run", actor_reference="actor", decision_reference="decision",
        authorized_at=NOW, mission_id="mission", execution_id=7,
        mission_status="COMPLETED", execution_status="COMPLETED",
        distribution_run_status="COMPLETED", external_post_id=None, external_url=None,
        platform="test", account_reference="account", destination="destination",
        result_metadata=None, failure_category=None, error_summary=None,
        distribution_run_completed_at=NOW, execution_completed_at=NOW,
        mission_completed_at=NOW, terminal_classification="TERMINAL",
        success_failure_classification="SUCCESS", execution_observation_policy_version="policy",
        execution_observation_contract_version="m11a14-economic-experiment-execution-observation-v1",
        execution_observation_semantics="frozen", created_at=NOW,
    )
    values.update(changes)
    return EconomicRecommendationExperimentObservation(**values)


class _Projection:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.requests = []

    def project(self, request):
        self.requests.append(request)
        return self.rows


class _Db:
    def __getattr__(self, name):
        if name in {"commit", "rollback", "flush", "add"}:
            raise AssertionError(f"M11A16 must not call {name}")
        raise AttributeError(name)


def _source(run="run", currency="USD", amount=Decimal("12.50")):
    return NetRealizedRevenueProjectionRow(
        currency=currency, net_realized_commission=amount,
        dimensions=(("distribution_run", run),),
        semantics=NET_REALIZED_REVENUE_PROJECTION_SEMANTICS,
    )


def _request(*observations):
    return EconomicRecommendationExperimentEconomicEvidenceRequest(
        observations, EconomicRecommendationExperimentEconomicEvidencePolicy("v1"),
    )


def test_requires_exact_m11a15_model_and_tuple_request():
    observation = _observation()
    assert validate_observation(observation) is observation
    with pytest.raises(ValueError, match="observation type"):
        validate_observation(SimpleNamespace(**vars(observation)))
    with pytest.raises(ValueError, match="observations must be a tuple"):
        EconomicRecommendationExperimentEconomicEvidenceRequest([], EconomicRecommendationExperimentEconomicEvidencePolicy("v1")).normalized()


def test_matching_source_preserves_complete_lineage_dimensions_and_semantics():
    observation = _observation()
    projection = _Projection((_source(),))
    row = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=projection).resolve(_request(observation))[0]
    assert projection.requests[0].dimensions == ("distribution_run",)
    assert row.evidence_resolution_classification == RESOLVED
    assert row.net_realized_commission == Decimal("12.50") and row.currency == "USD"
    assert row.source_dimensions == (("distribution_run", "run"),)
    assert row.source_projection_semantics == NET_REALIZED_REVENUE_PROJECTION_SEMANTICS
    assert (row.observation_fingerprint, row.experiment_reference, row.activation_reference, row.distribution_run_id, row.mission_id, row.execution_id) == (observation.observation_fingerprint, "experiment", "activation", "run", "mission", 7)
    assert (row.mission_status, row.execution_status, row.distribution_run_status, row.terminal_classification, row.success_failure_classification) == ("COMPLETED", "COMPLETED", "COMPLETED", "TERMINAL", "SUCCESS")


def test_zero_matching_evidence_is_resolved_not_no_evidence():
    row = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=_Projection((_source(amount=Decimal("0")),))).resolve(_request(_observation()))[0]
    assert row.evidence_resolution_classification == RESOLVED and row.net_realized_commission == Decimal("0") and row.currency == "USD"


def test_no_matching_source_has_canonical_source_less_representation():
    row = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=_Projection(())).resolve(_request(_observation()))[0]
    assert row.evidence_resolution_classification == NO_EVIDENCE
    assert row.net_realized_commission is None and row.currency is None
    assert row.source_dimensions == (("distribution_run", "run"),)


def test_multiple_currencies_remain_separate_in_source_order_without_aggregation():
    rows = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=_Projection((_source(currency="EUR", amount=Decimal("2")), _source(currency="USD", amount=Decimal("3"))))).resolve(_request(_observation()))
    assert [(row.currency, row.net_realized_commission) for row in rows] == [("EUR", Decimal("2")), ("USD", Decimal("3"))]


def test_distinct_observation_snapshots_same_run_remain_distinct_and_caller_order_is_preserved():
    second = _observation(id="second", observation_fingerprint="b" * 64)
    first = _observation()
    rows = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=_Projection((_source(),))).resolve(_request(second, first))
    assert [row.observation_fingerprint for row in rows] == ["b" * 64, "a" * 64]


def test_output_has_no_clock_or_outcome_winner_fields_and_service_writes_nothing():
    row = EconomicRecommendationExperimentEconomicEvidenceService(_Db(), projection_service=_Projection((_source(),))).resolve(_request(_observation()))[0]
    assert not ({"created_at", "observed_at", "success", "outcome", "winner"} & set(vars(row)))
