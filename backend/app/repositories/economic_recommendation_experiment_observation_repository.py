"""Narrow persistence primitives for immutable experiment observations."""

from app.models.economic_recommendation_experiment_observation import EconomicRecommendationExperimentObservation


class EconomicRecommendationExperimentObservationRepository:
    def __init__(self, db):
        self.db = db

    def get_by_fingerprint(self, fingerprint):
        return self.db.query(EconomicRecommendationExperimentObservation).filter_by(observation_fingerprint=fingerprint).one_or_none()

    def add(self, observation):
        self.db.add(observation)
        self.db.flush()
        return observation
