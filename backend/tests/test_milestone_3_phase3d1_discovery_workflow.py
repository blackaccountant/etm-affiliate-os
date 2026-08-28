import json
from decimal import Decimal

import httpx
import pytest

from app.database.session import SessionLocal
from app.discovery.adapters.base import AdapterDiscoveryResult, DiscoveryEvidence
from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, DiscoveryInputType, DiscoveryRunCreate, DiscoveryRunStatus, EvidenceObservationCreate, VerificationStatus
from app.models.affiliate_program import AffiliateProgram
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.product import Product
from app.registry.default_workflows import create_workflow_registry
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.retry.retry_policy import RetryPolicy
from app.retry.retry_scanner import RetryScanner
from app.scheduler.scheduler import Scheduler
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationResult, DiscoveryRunOrchestrationService
from app.services.official_site_discovery_service import OfficialSiteDiscoveryService
from app.task_queue.task import Task
from app.workflows.affiliate.discovery_run_workflow import AffiliateDiscoveryRunWorkflow
from app.workflow_engine.workflow_result import WorkflowResult
from app.workforce.default_workers import create_default_workers


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Phase 3D1 workflow tests must not use network access")

    monkeypatch.setattr(httpx, "get", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch_with_metadata", fail_network)


def create_run(db_session, status=DiscoveryRunStatus.CREATED, input_type=DiscoveryInputType.URL):
    run = DiscoveryRunRepository(db_session).create(DiscoveryRunCreate(
        input_type=input_type, input_value="https://acme.example",
    ))
    if status is not DiscoveryRunStatus.CREATED:
        run = DiscoveryRunRepository(db_session).update_status(run.id, status)
    return run


def create_candidate(db_session, run, name="program", selected=False):
    candidate = DiscoveryCandidateRepository(db_session).create(run.id, DiscoveryCandidateCreate(
        source_adapter="official_site", source_type="official_site", source_url="https://acme.example/affiliate",
        canonical_domain="acme.example", program_identity_key=f"program:{name}", dedupe_key=f"candidate:{name}",
        commission_model=CommissionModel.PERCENT, commission_percent=Decimal("30"), cookie_days=90,
        verification_status=VerificationStatus.VERIFIED,
        disposition=CandidateDisposition.SELECTED if selected else CandidateDisposition.VERIFIED,
        confidence=90, score=80,
    ))
    EvidenceObservationRepository(db_session).create(EvidenceObservationCreate(
        candidate_id=candidate.id, claim_type="commission_percent", observed_value=30,
        source_url=candidate.source_url, source_type="official_site", excerpt="Earn 30%.",
        http_status=200, content_hash=f"hash-{name}", extractor="test", extractor_version="1", confidence=90,
    ))
    return candidate


class StaticAdapter:
    name = "official_site"
    source_type = "official_site"
    extractor = "official-site-parser"
    extractor_version = "test-1"

    def discover(self, source):
        candidate = DiscoveryCandidateCreate(
            source_adapter=self.name, source_type=self.source_type, source_url=f"{source}/affiliate",
            canonical_domain="acme.example", program_identity_key="program:acme", dedupe_key="candidate:acme",
            commission_model=CommissionModel.PERCENT, commission_percent=Decimal("30"), cookie_days=90,
            verification_status=VerificationStatus.VERIFIED, disposition=CandidateDisposition.VERIFIED,
            confidence=90,
        )
        evidence = DiscoveryEvidence("commission_percent", 30, f"{source}/affiliate", "Earn 30%.", 200, "stable-hash", 90)
        return AdapterDiscoveryResult(candidate=candidate, evidence=(evidence,))


class PersistThenFailIngestion(OfficialSiteDiscoveryService):
    def __init__(self, db, plan):
        super().__init__(db, adapter=StaticAdapter())
        self.plan = plan

    def ingest(self, run_id, url):
        result = super().ingest(run_id, url)
        self.plan["calls"] += 1
        if self.plan["error"] and (not self.plan["fail_once"] or self.plan["calls"] == 1):
            raise RuntimeError(self.plan["error"])
        return result


class NoCandidateIngestion:
    def __init__(self):
        self.calls = 0

    def ingest(self, *args):
        self.calls += 1
        return None


class NeverIngest:
    def __init__(self):
        self.calls = 0

    def ingest(self, *args):
        self.calls += 1
        raise AssertionError("completed/running/failed runs must not ingest")


def workflow(session_factory, ingestion=None, captured=None):
    def factory(db):
        configured_ingestion = ingestion(db) if callable(ingestion) else ingestion
        service = DiscoveryRunOrchestrationService(db, ingestion=configured_ingestion or NoCandidateIngestion())
        if captured is not None:
            captured.append(service)
        return service

    return AffiliateDiscoveryRunWorkflow(session_factory=session_factory, orchestration_factory=factory)


def failing_ingestion(error, fail_once=False):
    plan = {"error": error, "fail_once": fail_once, "calls": 0}
    return plan, lambda db: PersistThenFailIngestion(db, plan)


def fresh_run(db_session, run_id):
    db_session.expire_all()
    return db_session.get(DiscoveryRun, run_id)


def test_registry_constructor_and_product_hunter_contract(db_session_factory, monkeypatch):
    def fail_default_session():
        raise AssertionError("configured SessionLocal must not be opened during construction")

    monkeypatch.setattr("app.workflows.affiliate.discovery_run_workflow.SessionLocal", fail_default_session)
    subject = AffiliateDiscoveryRunWorkflow(session_factory=db_session_factory)
    registry = create_workflow_registry().all()
    assert subject.session_factory is db_session_factory
    assert {"affiliate_discovery", "product_discovery", "affiliate_discovery_run"} <= set(registry)
    hunter = next(worker for worker in create_default_workers() if worker.name == "Product Hunter")
    assert "affiliate_research" in hunter.capabilities


def test_required_run_id_default_policy_propagation_and_json_safe_success(db_session, db_session_factory):
    run = create_run(db_session, status=DiscoveryRunStatus.COMPLETED)
    calls = []

    class RecordingOrchestrator:
        def __init__(self, db):
            self.db = db

        def execute(self, *args, **kwargs):
            calls.append((args, kwargs))
            return DiscoveryRunOrchestrationResult(self.db.get(DiscoveryRun, args[0]), ("ranked",), ("selected",))

    subject = AffiliateDiscoveryRunWorkflow(session_factory=db_session_factory, orchestration_factory=RecordingOrchestrator)
    assert subject.execute({}).success is False
    result = subject.execute({"discovery_run_id": run.id})
    custom = subject.execute({"discovery_run_id": run.id, "top_n": 2, "minimum_score": 50, "minimum_evidence_confidence": 80})
    assert isinstance(result, WorkflowResult) and result.success is True
    assert result.data["ranked_candidate_ids"] == ["ranked"] and result.data["selected_candidate_ids"] == ["selected"]
    assert calls[0] == ((run.id, 1, 40, 70), {"defer_terminal_failure": True})
    assert calls[1] == ((run.id, 2, 50, 80), {"defer_terminal_failure": True})
    assert custom.success is True and json.dumps(result.data)


def test_execute_owns_one_session_and_closes_on_success_and_failure(db_session, db_session_factory):
    run = create_run(db_session)
    sessions = []

    class TrackedSession:
        def __init__(self):
            self.session, self.closed = db_session_factory(), False

        def close(self):
            self.closed = True
            self.session.close()

        def __getattr__(self, name):
            return getattr(self.session, name)

    def factory():
        sessions.append(TrackedSession())
        return sessions[-1]

    assert workflow(factory, NoCandidateIngestion()).execute({"discovery_run_id": run.id}).success is True
    assert len(sessions) == 1 and sessions[0].closed is True
    failed = create_run(db_session)
    _, failing = failing_ingestion("network timeout")
    assert workflow(factory, failing).execute({"discovery_run_id": failed.id}).success is False
    assert len(sessions) == 2 and sessions[1].closed is True


@pytest.mark.parametrize(
    ("error", "canonical_fragment"),
    [
        ("network timeout", "network timeout"),
        ("connection refused", "connection refused"),
        ("HTTP 429 Too Many Requests", "rate limit"),
        ("provider unavailable", "upstream unavailable"),
    ],
)
def test_retryable_failures_are_canonicalized_and_restored_to_created(db_session, db_session_factory, error, canonical_fragment):
    run = create_run(db_session)
    _, failing = failing_ingestion(error)
    subject = workflow(db_session_factory, failing)
    result = subject.execute({"discovery_run_id": run.id, "retry_count": 0, "max_retries": 3})
    refreshed = fresh_run(db_session, run.id)
    assert result.success is False and result.data["retryable"] is True
    assert canonical_fragment in result.errors[0].lower()
    assert refreshed.status == DiscoveryRunStatus.CREATED.value and refreshed.last_error == result.errors[0]
    assert refreshed.completed_at is None


def test_retry_preserves_partial_work_dedupes_and_completes(db_session, db_session_factory):
    run = create_run(db_session)
    plan, ingestion = failing_ingestion("network timeout", fail_once=True)
    result = workflow(db_session_factory, ingestion).execute({"discovery_run_id": run.id, "retry_count": 0, "max_retries": 3})
    assert result.success is False and fresh_run(db_session, run.id).status == "CREATED"
    first_candidate_count = db_session.query(DiscoveryCandidate).filter_by(run_id=run.id).count()
    first_evidence_count = db_session.query(EvidenceObservation).count()
    retried = workflow(db_session_factory, ingestion).execute({"discovery_run_id": run.id, "retry_count": 1, "max_retries": 3})
    refreshed = fresh_run(db_session, run.id)
    assert retried.success is True and refreshed.status == "COMPLETED" and plan["calls"] == 2
    assert db_session.query(DiscoveryCandidate).filter_by(run_id=run.id).count() == first_candidate_count == 1
    assert db_session.query(EvidenceObservation).count() == first_evidence_count == 1
    assert refreshed.candidate_count == refreshed.verified_count == refreshed.selected_count == 1


def test_permanent_and_exhausted_failures_are_terminal(db_session, db_session_factory):
    permanent = create_run(db_session, input_type=DiscoveryInputType.MARKET)
    permanent_result = workflow(db_session_factory, NoCandidateIngestion()).execute({"discovery_run_id": permanent.id})
    assert permanent_result.success is False and fresh_run(db_session, permanent.id).status == "FAILED"
    exhausted = create_run(db_session)
    _, failing = failing_ingestion("network timeout")
    exhausted_result = workflow(db_session_factory, failing).execute({"discovery_run_id": exhausted.id, "retry_count": 2, "max_retries": 3})
    assert exhausted_result.success is False and exhausted_result.data["retryable"] is True
    assert fresh_run(db_session, exhausted.id).status == "FAILED"


def test_retry_finality_matches_frozen_retry_policy():
    subject = AffiliateDiscoveryRunWorkflow(session_factory=SessionLocal)
    for retry_count, max_retries in ((0, 3), (1, 3), (2, 3), (0, 0), (3, 5)):
        task = Task("affiliate_discovery_run", {}, max_retries=max_retries)
        task.retry_count = retry_count
        assert subject._another_retry_remains(retry_count, max_retries) is RetryPolicy().execute_retry(task)


def test_no_candidate_completed_and_completed_run_is_idempotent(db_session, db_session_factory):
    empty = create_run(db_session)
    no_candidates = NoCandidateIngestion()
    result = workflow(db_session_factory, no_candidates).execute({"discovery_run_id": empty.id})
    assert result.success is True and result.data["candidate_count"] == result.data["verified_count"] == result.data["selected_count"] == 0
    assert result.data["ranked_candidate_ids"] == result.data["selected_candidate_ids"] == []
    completed = create_run(db_session, status=DiscoveryRunStatus.COMPLETED)
    candidate = create_candidate(db_session, completed, selected=True)
    DiscoveryRunRepository(db_session).update_counters(completed.id, candidate_count=1, verified_count=1, selected_count=1)
    never = NeverIngest()
    before = (candidate.updated_at, db_session.query(EvidenceObservation).filter_by(candidate_id=candidate.id).count())
    repeated = workflow(db_session_factory, never).execute({"discovery_run_id": completed.id})
    after = db_session.get(DiscoveryCandidate, candidate.id)
    assert repeated.success is True and never.calls == 0
    assert (after.updated_at, db_session.query(EvidenceObservation).filter_by(candidate_id=candidate.id).count()) == before


@pytest.mark.parametrize("payload_update", [{"top_n": 0}, {"minimum_score": 101}, {"minimum_evidence_confidence": 101}])
def test_invalid_policy_on_created_run_marks_run_failed(db_session, db_session_factory, payload_update):
    run = create_run(db_session)
    no_ingestion = NoCandidateIngestion()
    subject = workflow(db_session_factory, no_ingestion)
    result = subject.execute({"discovery_run_id": run.id, **payload_update})
    refreshed = fresh_run(db_session, run.id)
    assert result.success is False
    assert refreshed.status == DiscoveryRunStatus.FAILED.value
    assert refreshed.last_error is not None
    assert any(key in refreshed.last_error.lower() for key in ["top_n", "minimum_score", "minimum_evidence_confidence"])
    assert no_ingestion.calls == 0


@pytest.mark.parametrize("payload_update", [{"retry_count": -1}, {"max_retries": -1}, {"max_retries": "invalid"}])
def test_invalid_retry_metadata_on_created_run_marks_run_failed(db_session, db_session_factory, payload_update):
    run = create_run(db_session)
    no_ingestion = NoCandidateIngestion()
    subject = workflow(db_session_factory, no_ingestion)
    result = subject.execute({"discovery_run_id": run.id, **payload_update})
    refreshed = fresh_run(db_session, run.id)
    assert result.success is False
    assert refreshed.status == DiscoveryRunStatus.FAILED.value
    assert refreshed.last_error is not None
    assert any(key in refreshed.last_error.lower() for key in ["retry_count", "max_retries", "integer"])
    assert no_ingestion.calls == 0


def test_invalid_policy_failure_closes_session_on_created_run(db_session, db_session_factory):
    run = create_run(db_session)
    sessions = []

    class TrackedSession:
        def __init__(self):
            self.session, self.closed = db_session_factory(), False

        def close(self):
            self.closed = True
            self.session.close()

        def __getattr__(self, name):
            return getattr(self.session, name)

    def factory():
        sessions.append(TrackedSession())
        return sessions[-1]

    result = workflow(factory, NoCandidateIngestion()).execute({"discovery_run_id": run.id, "top_n": 0})
    assert result.success is False
    assert len(sessions) == 1 and sessions[0].closed is True


def test_retry_scanner_restores_complete_discovery_policy_payload_from_execution_input_data():
    class RetryExecution:
        id = 42
        workflow_name = "affiliate_discovery_run"
        mission_id = "mission-7"
        worker_name = "Product Hunter"
        retry_count = 1
        max_retries = 3
        failure_type = "NETWORK"
        status = "QUEUED"
        input_data = json.dumps({
            "discovery_run_id": "run-abc",
            "top_n": 2,
            "minimum_score": 55,
            "minimum_evidence_confidence": 80,
        })

    class ScannerService:
        def __init__(self, execution):
            self.execution = execution

        def get_retry_queue(self, limit):
            return [self.execution]

        def claim_retry(self, execution):
            execution.status = "RETRYING"
            return execution

    execution = RetryExecution()
    tasks = RetryScanner(ScannerService(execution), Scheduler()).scan_once(limit=4)
    assert len(tasks) == 1
    payload = tasks[0].payload
    assert payload["discovery_run_id"] == "run-abc"
    assert payload["top_n"] == 2
    assert payload["minimum_score"] == 55
    assert payload["minimum_evidence_confidence"] == 80
    assert payload["retry_count"] == 1
    assert payload["max_retries"] == 3
    assert payload["mission_id"] == "mission-7"
    assert payload["execution_id"] == 42
    assert payload["worker_name"] == "Product Hunter"


def test_phase_3d2_mission_metadata_contract_is_json_safe():
    run_id = "run-123"
    metadata = {
        "discovery_run_id": run_id,
        "top_n": 1,
        "minimum_score": 40,
        "minimum_evidence_confidence": 70,
    }
    assert json.loads(json.dumps(metadata)) == metadata


def test_running_and_existing_failed_runs_refuse_reentry_without_downstream_writes(db_session, db_session_factory):
    running = create_run(db_session, status=DiscoveryRunStatus.RUNNING)
    failed = create_run(db_session, status=DiscoveryRunStatus.FAILED)
    never = NeverIngest()
    subject = workflow(db_session_factory, never)
    running_result = subject.execute({"discovery_run_id": running.id})
    failed_result = subject.execute({"discovery_run_id": failed.id})
    assert running_result.success is failed_result.success is False and never.calls == 0
    assert fresh_run(db_session, running.id).status == "RUNNING"
    assert fresh_run(db_session, failed.id).status == "FAILED"
    assert db_session.query(Product).count() == 0 and db_session.query(AffiliateProgram).count() == 0
