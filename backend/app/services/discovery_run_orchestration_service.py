"""Durable URL discovery-run orchestration without API or mission coupling."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.discovery.contracts import DiscoveryInputType, DiscoveryRunStatus, VerificationStatus
from app.models.discovery import DiscoveryRun
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.services.discovery_candidate_scoring_service import DiscoveryCandidateScoringService, DiscoveryRankingService, DiscoveryWinnerSelectionService
from app.services.official_site_discovery_service import OfficialSiteDiscoveryService


@dataclass(frozen=True)
class DiscoveryRunOrchestrationResult:
    run: DiscoveryRun
    ranked_candidate_ids: tuple[str, ...]
    selected_candidate_ids: tuple[str, ...]


class DiscoveryRunOrchestrationService:
    """Compose accepted discovery components for one URL-backed durable run."""

    def __init__(
        self,
        db: Session,
        ingestion: OfficialSiteDiscoveryService | None = None,
        scoring: DiscoveryCandidateScoringService | None = None,
        ranking: DiscoveryRankingService | None = None,
        selection: DiscoveryWinnerSelectionService | None = None,
    ):
        self.runs = DiscoveryRunRepository(db)
        self.candidates = DiscoveryCandidateRepository(db)
        self.ingestion = ingestion or OfficialSiteDiscoveryService(db)
        self.scoring = scoring or DiscoveryCandidateScoringService(db)
        self.ranking = ranking or DiscoveryRankingService(db)
        self.selection = selection or DiscoveryWinnerSelectionService(db, self.ranking)

    def execute(
        self,
        run_id: str,
        top_n: int = 1,
        minimum_score: int = 40,
        minimum_evidence_confidence: int = 70,
        defer_terminal_failure: bool = False,
    ) -> DiscoveryRunOrchestrationResult:
        run = self.runs.get_by_id(run_id)
        self._validate(run, top_n, minimum_score, minimum_evidence_confidence)
        assert run is not None
        if run.status == DiscoveryRunStatus.COMPLETED.value:
            return self._durable_result(run_id)
        if run.status == DiscoveryRunStatus.RUNNING.value:
            raise RuntimeError("discovery run is already running")
        if run.status == DiscoveryRunStatus.FAILED.value:
            raise RuntimeError("failed discovery run requires explicit retry orchestration")
        if run.input_type != DiscoveryInputType.URL.value:
            message = f"unsupported discovery input type: {run.input_type}"
            self.runs.update_status(run_id, DiscoveryRunStatus.FAILED, message)
            raise ValueError(message)

        self.runs.update_status(run_id, DiscoveryRunStatus.RUNNING)
        try:
            self.ingestion.ingest(run_id, run.input_value)
            for candidate in self.candidates.list_by_run(run_id):
                self.scoring.score_candidate(candidate.id)
            self.ranking.rank(run_id)
            self.selection.apply_selection(run_id, top_n, minimum_score, minimum_evidence_confidence)
            self._assert_counters(run_id)
            self.runs.update_status(run_id, DiscoveryRunStatus.COMPLETED)
            return self._durable_result(run_id)
        except Exception as original_error:
            try:
                # Mission-backed retries need a non-terminal business state that
                # the existing orchestrator can safely execute again.
                target = DiscoveryRunStatus.CREATED if defer_terminal_failure else DiscoveryRunStatus.FAILED
                self.runs.update_status(run_id, target, str(original_error))
            except Exception as finalization_error:
                raise RuntimeError("discovery run failure could not be persisted") from finalization_error
            raise

    @staticmethod
    def _validate(run, top_n: int, minimum_score: int, minimum_confidence: int) -> None:
        if run is None:
            raise ValueError("discovery run does not exist")
        if not run.input_value or not run.input_value.strip():
            raise ValueError("discovery run input_value is required")
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        if not 0 <= minimum_score <= 100:
            raise ValueError("minimum_score must be between 0 and 100")
        if not 0 <= minimum_confidence <= 100:
            raise ValueError("minimum_evidence_confidence must be between 0 and 100")

    def _durable_result(self, run_id: str) -> DiscoveryRunOrchestrationResult:
        run = self.runs.get_by_id(run_id)
        if run is None:
            raise ValueError("discovery run does not exist")
        ranked = self.ranking.rank(run_id)
        selected = self.candidates.list_selected_by_run(run_id)
        return DiscoveryRunOrchestrationResult(
            run=run,
            ranked_candidate_ids=tuple(item.candidate.id for item in ranked),
            selected_candidate_ids=tuple(item.id for item in selected),
        )

    def _assert_counters(self, run_id: str) -> None:
        run = self.runs.get_by_id(run_id)
        candidates = self.candidates.list_by_run(run_id)
        if run is None:
            raise ValueError("discovery run does not exist")
        expected = (
            len(candidates),
            sum(item.verification_status == VerificationStatus.VERIFIED.value for item in candidates),
            len(self.candidates.list_selected_by_run(run_id)),
        )
        actual = (run.candidate_count, run.verified_count, run.selected_count)
        if actual != expected:
            raise RuntimeError("discovery run counters are inconsistent")
