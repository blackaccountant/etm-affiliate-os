"""Persist exact M11A14 observations without re-reading their source records."""

from sqlalchemy.exc import IntegrityError

from app.models.economic_recommendation_experiment_observation import EconomicRecommendationExperimentObservation
from app.optimization.economic_recommendation_experiment_observation_persistence_contracts import (
    EconomicRecommendationExperimentObservationFingerprintConflict,
    EconomicRecommendationExperimentObservationPersistenceRequest,
    SOURCE_FIELDS,
    observation_fingerprint,
    observation_snapshot,
)
from app.repositories.economic_recommendation_experiment_observation_repository import EconomicRecommendationExperimentObservationRepository


class EconomicRecommendationExperimentObservationPersistenceService:
    def __init__(self, db, *, repository=None):
        self.db = db
        self._observations = EconomicRecommendationExperimentObservationRepository(db) if repository is None else repository

    @staticmethod
    def _matches(existing, source, fingerprint):
        return (
            existing.observation_fingerprint == fingerprint
            and all(getattr(existing, field) == getattr(source, field) for field in SOURCE_FIELDS)
        )

    @staticmethod
    def _new(source, fingerprint):
        return EconomicRecommendationExperimentObservation(
            **{field: getattr(source, field) for field in SOURCE_FIELDS},
            observation_fingerprint=fingerprint,
        )

    def _persist_one(self, source):
        fingerprint = observation_fingerprint(source)
        existing = self._observations.get_by_fingerprint(fingerprint)
        if existing is not None:
            if not self._matches(existing, source, fingerprint):
                raise EconomicRecommendationExperimentObservationFingerprintConflict("immutable observation fingerprint conflict")
            return existing
        record = self._new(source, fingerprint)
        try:
            self._observations.add(record)
            self.db.commit()
            self.db.refresh(record)
            return record
        except IntegrityError:
            self.db.rollback()
            existing = self._observations.get_by_fingerprint(fingerprint)
            if existing is None or not self._matches(existing, source, fingerprint):
                raise EconomicRecommendationExperimentObservationFingerprintConflict("immutable observation fingerprint conflict")
            return existing

    def persist(self, request: EconomicRecommendationExperimentObservationPersistenceRequest):
        normalized = request.normalized()
        return tuple(self._persist_one(row) for row in normalized.execution_observation_rows)
