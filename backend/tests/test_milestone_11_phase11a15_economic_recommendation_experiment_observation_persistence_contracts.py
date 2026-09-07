"""Focused M11A15 immutable observation persistence contracts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.optimization.economic_recommendation_experiment_execution_observation_contracts import EconomicRecommendationExperimentExecutionObservationRow
from app.optimization.economic_recommendation_experiment_observation_persistence_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_OBSERVATION_PERSISTENCE_CONTRACT_VERSION,
    EconomicRecommendationExperimentObservationPersistencePolicy,
    EconomicRecommendationExperimentObservationPersistenceRequest,
    EconomicRecommendationExperimentObservationFingerprintConflict,
    observation_fingerprint,
    observation_snapshot,
    validate_execution_observation_row,
)
from app.services.economic_recommendation_experiment_observation_persistence_service import EconomicRecommendationExperimentObservationPersistenceService

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def _source(**changes):
    values = dict(experiment_reference="experiment", activation_reference="activation", distribution_run_id="run", actor_reference="actor", decision_reference="decision", authorized_at=NOW, mission_id="mission", execution_id=7, mission_status="COMPLETED", execution_status="COMPLETED", distribution_run_status="COMPLETED", external_post_id="post", external_url="https://example.test", platform="test", account_reference="account", destination="destination", result_metadata={"a": 1, "b": [2]}, failure_category=None, error_summary=None, distribution_run_completed_at=NOW, execution_completed_at=NOW, mission_completed_at=NOW, terminal_classification="TERMINAL", success_failure_classification="SUCCESS", execution_observation_policy_version="policy", execution_observation_contract_version="m11a14-economic-experiment-execution-observation-v1", execution_observation_semantics="consume exact frozen M11A12 execution-binding rows; deterministically resolve their M11A13 durable Mission through the established distribution mission idempotency key; read the canonical latest Execution using the established ExecutionRepository.get_by_mission_id() descending-ID ordering; read the referenced persisted DistributionRun; and emit an immutable deterministic execution/publication observation preserving experiment lineage. DistributionRun status is authoritative for publication outcome. No mutation, activation, scheduling, dispatch, publishing, attribution, scoring, winner selection, or economic inference.")
    values.update(changes)
    return EconomicRecommendationExperimentExecutionObservationRow(**values)


class _Repo:
    def __init__(self): self.rows = {}
    def get_by_fingerprint(self, fingerprint): return self.rows.get(fingerprint)
    def add(self, row): self.rows[row.observation_fingerprint] = row; return row


class _Db:
    def __init__(self): self.commits = self.rollbacks = 0
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def refresh(self, row): pass


def _request(*rows):
    return EconomicRecommendationExperimentObservationPersistenceRequest(rows, EconomicRecommendationExperimentObservationPersistencePolicy("v1"))


def test_contract_metadata_and_exact_source_type():
    assert ECONOMIC_RECOMMENDATION_EXPERIMENT_OBSERVATION_PERSISTENCE_CONTRACT_VERSION == "m11a15-economic-experiment-observation-persistence-v1"
    source = _source()
    assert validate_execution_observation_row(source) is source
    with pytest.raises(ValueError, match="row type"):
        validate_execution_observation_row(SimpleNamespace(**vars(_source())))
    with pytest.raises(ValueError, match="execution_observation_rows must be a tuple"):
        EconomicRecommendationExperimentObservationPersistenceRequest([], EconomicRecommendationExperimentObservationPersistencePolicy("v1")).normalized()


@pytest.mark.parametrize("field, value, message", [("execution_observation_semantics", "wrong", "semantics"), ("execution_observation_contract_version", "wrong", "contract version")])
def test_bad_frozen_m11a14_metadata_is_rejected(field, value, message):
    with pytest.raises(ValueError, match=message): validate_execution_observation_row(_source(**{field: value}))


def test_fingerprint_is_deterministic_complete_and_json_order_independent():
    source = _source()
    assert observation_fingerprint(source) == observation_fingerprint(_source(result_metadata={"b": [2], "a": 1}))
    assert observation_fingerprint(source) != observation_fingerprint(_source(actor_reference="other"))
    assert observation_fingerprint(source) != observation_fingerprint(_source(external_url="https://other.test"))
    assert observation_fingerprint(source) != observation_fingerprint(_source(error_summary="failed"))
    assert observation_fingerprint(source) != observation_fingerprint(
        _source(distribution_run_completed_at=NOW + timedelta(seconds=1))
    )
    assert "created_at" not in observation_snapshot(source)


def test_exact_replay_is_idempotent_and_changed_same_execution_is_distinct():
    db, repo = _Db(), _Repo(); service = EconomicRecommendationExperimentObservationPersistenceService(db, repository=repo)
    first = service.persist(_request(_source()))[0]
    replay = service.persist(_request(_source()))[0]
    changed = service.persist(_request(_source(distribution_run_status="RECONCILIATION_REQUIRED", terminal_classification="NON_TERMINAL", success_failure_classification="UNRESOLVED")))[0]
    assert first is replay and len(repo.rows) == 2 and changed.execution_id == first.execution_id and changed.observation_fingerprint != first.observation_fingerprint


def test_snapshot_is_preserved_and_source_is_not_mutated():
    source = _source(); db, repo = _Db(), _Repo()
    stored = EconomicRecommendationExperimentObservationPersistenceService(db, repository=repo).persist(_request(source))[0]
    for field, value in vars(source).items():
        assert getattr(stored, field) == value
    assert stored.created_at is None or stored.created_at is not NOW
    assert source.result_metadata == {"a": 1, "b": [2]}


def test_same_fingerprint_with_nonidentical_persisted_snapshot_is_rejected():
    db, repo = _Db(), _Repo()
    service = EconomicRecommendationExperimentObservationPersistenceService(db, repository=repo)
    stored = service.persist(_request(_source()))[0]
    stored.destination = "tampered"
    with pytest.raises(EconomicRecommendationExperimentObservationFingerprintConflict, match="fingerprint conflict"):
        service.persist(_request(_source()))


def test_persistence_service_has_no_source_or_economic_dependencies():
    source = _source()
    db, repo = _Db(), _Repo()
    service = EconomicRecommendationExperimentObservationPersistenceService(db, repository=repo)
    service.persist(_request(source))
    assert db.commits == 1 and db.rollbacks == 0
    assert source.distribution_run_status == "COMPLETED"
