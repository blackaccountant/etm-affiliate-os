"""Read-only queries for the discovery API."""

from sqlalchemy.orm import Session

from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.services.discovery_candidate_scoring_service import DiscoveryRankingService


class DiscoveryQueryService:
    def __init__(self, db: Session, ranking: DiscoveryRankingService | None = None):
        self.runs = DiscoveryRunRepository(db)
        self.candidates = DiscoveryCandidateRepository(db)
        self.evidence = EvidenceObservationRepository(db)
        self.ranking_service = ranking or DiscoveryRankingService(db)

    def get_run(self, run_id):
        return self.runs.get_by_id(run_id)

    def list_candidates(self, run_id):
        return self.candidates.list_by_run(run_id)

    def get_candidate(self, candidate_id):
        return self.candidates.get_by_id(candidate_id)

    def list_evidence(self, candidate_id):
        return self.evidence.list_by_candidate(candidate_id)

    def ranking(self, run_id):
        return self.ranking_service.rank(run_id)

    def selected(self, run_id):
        return self.candidates.list_selected_by_run(run_id)
