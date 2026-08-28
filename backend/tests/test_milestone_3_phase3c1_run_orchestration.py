from decimal import Decimal

import pytest

from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, DiscoveryInputType, DiscoveryRunCreate, EvidenceObservationCreate, VerificationStatus
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.services.discovery_candidate_scoring_service import DiscoveryCandidateScoringService, DiscoveryRankingService, DiscoveryWinnerSelectionService
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService


def run(db_session, input_type=DiscoveryInputType.URL):
    return DiscoveryRunRepository(db_session).create(DiscoveryRunCreate(input_type=input_type, input_value="https://acme.example"))


def candidate(db_session, run_id, name, status=VerificationStatus.VERIFIED, confidence=90):
    record = DiscoveryCandidateRepository(db_session).create(run_id, DiscoveryCandidateCreate(
        source_adapter="official_site", source_type="official_site", source_url=f"https://acme.example/{name}",
        canonical_domain="acme.example", program_identity_key=f"program:{name}", dedupe_key=f"candidate:{name}",
        commission_model=CommissionModel.RECURRING_PERCENT, commission_percent=Decimal("30"), cookie_days=180,
        affiliate_network="Impact", verification_status=status,
        disposition=CandidateDisposition.VERIFIED if status is VerificationStatus.VERIFIED else CandidateDisposition.DISCOVERED,
        confidence=confidence,
    ))
    EvidenceObservationRepository(db_session).create(EvidenceObservationCreate(
        candidate_id=record.id, claim_type="commission_percent", observed_value=30,
        source_url=record.source_url, source_type="official_site", excerpt="Earn 30% recurring commission.",
        http_status=200, content_hash=f"hash-{name}", extractor="test", extractor_version="1", confidence=90,
    ))
    return record


class FakeIngestion:
    def __init__(self, db_session, events, mode="candidates"):
        self.db_session, self.events, self.mode, self.calls = db_session, events, mode, 0

    def ingest(self, run_id, url):
        current = DiscoveryRunRepository(self.db_session).get_by_id(run_id)
        assert current.status == "RUNNING"
        self.calls += 1
        self.events.append("ingestion")
        if self.mode == "raises_after_persist":
            candidate(self.db_session, run_id, "durable")
            raise RuntimeError("ingestion failed")
        if self.mode == "candidates":
            candidate(self.db_session, run_id, "verified")
            candidate(self.db_session, run_id, "partial", VerificationStatus.PARTIAL)


class RecordingScoring:
    def __init__(self, db_session, events, fail=False):
        self.actual, self.events, self.fail = DiscoveryCandidateScoringService(db_session), events, fail

    def score_candidate(self, candidate_id):
        self.events.append(f"score:{candidate_id}")
        if self.fail:
            raise RuntimeError("scoring failed")
        return self.actual.score_candidate(candidate_id)


class RecordingRanking:
    def __init__(self, db_session, events, fail=False):
        self.actual, self.events, self.fail = DiscoveryRankingService(db_session), events, fail

    def rank(self, run_id):
        self.events.append("ranking")
        if self.fail:
            raise RuntimeError("ranking failed")
        return self.actual.rank(run_id)


class RecordingSelection:
    def __init__(self, db_session, ranking, events, fail=False):
        self.actual, self.events, self.fail = DiscoveryWinnerSelectionService(db_session, ranking.actual), events, fail

    def apply_selection(self, *args):
        self.events.append("selection")
        if self.fail:
            raise RuntimeError("selection failed")
        return self.actual.apply_selection(*args)


def service(db_session, mode="candidates", failure=None):
    events = []
    ingestion = FakeIngestion(db_session, events, mode)
    scoring = RecordingScoring(db_session, events, failure == "scoring")
    ranking = RecordingRanking(db_session, events, failure == "ranking")
    selection = RecordingSelection(db_session, ranking, events, failure == "selection")
    return DiscoveryRunOrchestrationService(db_session, ingestion, scoring, ranking, selection), ingestion, events


def test_url_run_orders_components_scores_all_and_returns_durable_state(db_session):
    durable_run = run(db_session)
    subject, _, events = service(db_session)
    result = subject.execute(durable_run.id, top_n=1, minimum_score=40, minimum_evidence_confidence=70)
    assert events[0] == "ingestion" and events[1].startswith("score:") and events[2].startswith("score:")
    assert events.index("ranking") < events.index("selection")
    assert result.run.status == "COMPLETED" and result.run.completed_at is not None and result.run.last_error is None
    assert len(result.ranked_candidate_ids) == 2 and len(result.selected_candidate_ids) == 1
    selected = DiscoveryCandidateRepository(db_session).list_selected_by_run(durable_run.id)
    assert result.selected_candidate_ids == tuple(item.id for item in selected)
    assert (result.run.candidate_count, result.run.verified_count, result.run.selected_count) == (2, 1, 1)
    assert db_session.query(Product).count() == 0 and db_session.query(AffiliateProgram).count() == 0


def test_no_candidate_completed_run_is_empty_and_restart_idempotent(db_session):
    durable_run = run(db_session)
    subject, ingestion, _ = service(db_session, mode="none")
    first = subject.execute(durable_run.id)
    restarted, _, _ = service(db_session, mode="candidates")
    second = restarted.execute(durable_run.id)
    assert first.run.id == second.run.id and first.ranked_candidate_ids == second.ranked_candidate_ids == ()
    assert first.selected_candidate_ids == second.selected_candidate_ids == () and ingestion.calls == 1
    assert (second.run.candidate_count, second.run.verified_count, second.run.selected_count) == (0, 0, 0)


@pytest.mark.parametrize("input_type", [DiscoveryInputType.MARKET, DiscoveryInputType.NICHE, DiscoveryInputType.SEED])
def test_unsupported_input_is_failed_without_discovery(db_session, input_type):
    durable_run = run(db_session, input_type)
    subject, ingestion, _ = service(db_session)
    with pytest.raises(ValueError, match="unsupported discovery input type"):
        subject.execute(durable_run.id)
    assert ingestion.calls == 0 and DiscoveryRunRepository(db_session).get_by_id(durable_run.id).status == "FAILED"


def test_invalid_and_non_restartable_run_states_refuse_before_discovery(db_session):
    created = run(db_session)
    subject, ingestion, _ = service(db_session)
    with pytest.raises(ValueError, match="top_n"):
        subject.execute(created.id, top_n=0)
    with pytest.raises(ValueError, match="minimum_score"):
        subject.execute(created.id, minimum_score=101)
    with pytest.raises(ValueError, match="minimum_evidence_confidence"):
        subject.execute(created.id, minimum_evidence_confidence=-1)
    assert ingestion.calls == 0 and DiscoveryRunRepository(db_session).get_by_id(created.id).status == "CREATED"
    running = run(db_session)
    DiscoveryRunRepository(db_session).update_status(running.id, "RUNNING")
    with pytest.raises(RuntimeError, match="already running"):
        subject.execute(running.id)
    failed = run(db_session)
    DiscoveryRunRepository(db_session).update_status(failed.id, "FAILED", "old failure")
    with pytest.raises(RuntimeError, match="requires explicit retry"):
        subject.execute(failed.id)
    with pytest.raises(ValueError, match="does not exist"):
        subject.execute("missing")


@pytest.mark.parametrize("failure", ["scoring", "ranking", "selection"])
def test_execution_failures_finalize_run_and_preserve_durable_work(db_session, failure):
    durable_run = run(db_session)
    subject, _, _ = service(db_session, failure=failure)
    with pytest.raises(RuntimeError, match=failure + " failed"):
        subject.execute(durable_run.id)
    refreshed = DiscoveryRunRepository(db_session).get_by_id(durable_run.id)
    assert refreshed.status == "FAILED" and failure in refreshed.last_error and refreshed.completed_at is not None
    assert len(DiscoveryCandidateRepository(db_session).list_by_run(durable_run.id)) == 2


def test_ingestion_failure_marks_failed_but_keeps_partial_durable_observations(db_session):
    durable_run = run(db_session)
    subject, _, _ = service(db_session, mode="raises_after_persist")
    with pytest.raises(RuntimeError, match="ingestion failed"):
        subject.execute(durable_run.id)
    assert DiscoveryRunRepository(db_session).get_by_id(durable_run.id).status == "FAILED"
    assert len(DiscoveryCandidateRepository(db_session).list_by_run(durable_run.id)) == 1
