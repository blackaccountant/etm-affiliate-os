from datetime import timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.discovery import router
from app.dependencies import get_db, get_discovery_run_orchestration_service
from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, DiscoveryInputType, DiscoveryRunCreate, DiscoveryRunStatus, EvidenceObservationCreate, VerificationStatus
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationResult


def api_client(db_session_factory, orchestration=None):
    app = FastAPI()
    app.include_router(router, prefix="/discovery")
    def override_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    if orchestration:
        app.dependency_overrides[get_discovery_run_orchestration_service] = lambda: orchestration
    return TestClient(app)


def create_run(db_session, key=None, status=DiscoveryRunStatus.CREATED):
    record = DiscoveryRunRepository(db_session).create(DiscoveryRunCreate(input_type=DiscoveryInputType.URL, input_value="https://acme.example", idempotency_key=key))
    if status is not DiscoveryRunStatus.CREATED:
        record = DiscoveryRunRepository(db_session).update_status(record.id, status)
    return record


def create_candidate(db_session, run, name, selected=False, partial=False):
    candidate = DiscoveryCandidateRepository(db_session).create(run.id, DiscoveryCandidateCreate(
        source_adapter="official_site", source_type="official_site", source_url=f"https://acme.example/{name}",
        canonical_domain="acme.example", program_identity_key=f"program:{name}", dedupe_key=f"candidate:{name}",
        commission_model=CommissionModel.PERCENT, commission_percent=Decimal("30"), cookie_days=90,
        verification_status=VerificationStatus.PARTIAL if partial else VerificationStatus.VERIFIED,
        disposition=CandidateDisposition.SELECTED if selected else CandidateDisposition.VERIFIED,
        confidence=80, score=60, score_breakdown={"basis": "affiliate_economics_only"}, score_reasons=[{"title": "test", "points": 1}],
    ))
    EvidenceObservationRepository(db_session).create(EvidenceObservationCreate(
        candidate_id=candidate.id, claim_type="commission_percent", observed_value=30, source_url=candidate.source_url,
        source_type="official_site", excerpt="Earn 30%.", http_status=200, content_hash=f"hash-{name}", extractor="test", extractor_version="1", confidence=90,
    ))
    return candidate


def test_create_idempotent_and_get_run_are_isolated(db_session, db_session_factory):
    client = api_client(db_session_factory)
    payload = {"input_type": "URL", "input_value": "https://acme.example", "idempotency_key": "api-key"}
    first = client.post("/discovery/runs", json=payload)
    second = client.post("/discovery/runs", json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["created_at"].endswith(("+00:00", "Z"))
    assert client.get(f"/discovery/runs/{first.json()['id']}").status_code == 200
    assert client.get("/discovery/runs/missing").status_code == 404
    assert client.post("/discovery/runs", json={"input_type": "URL", "input_value": ""}).status_code == 422


def test_candidate_ranking_selected_and_evidence_reads_are_durable(db_session, db_session_factory):
    run = create_run(db_session)
    first = create_candidate(db_session, run, "a", selected=True)
    second = create_candidate(db_session, run, "b", partial=True)
    DiscoveryRunRepository(db_session).update_counters(run.id, candidate_count=2, verified_count=1, selected_count=1)
    client = api_client(db_session_factory)
    candidates = client.get(f"/discovery/runs/{run.id}/candidates")
    ranking = client.get(f"/discovery/runs/{run.id}/ranking")
    selected = client.get(f"/discovery/runs/{run.id}/selected")
    evidence = client.get(f"/discovery/candidates/{first.id}/evidence")
    assert candidates.status_code == 200 and [item["id"] for item in candidates.json()] == [first.id, second.id]
    assert candidates.json()[0]["commission_percent"] == "30.00"
    assert candidates.json()[0]["verification_status"] == "VERIFIED"
    assert ranking.json()["items"][0]["rank"] == 1 and ranking.json()["items"][0]["candidate"]["id"] == first.id
    assert ranking.json()["items"][0]["evidence_count"] == 1
    assert [item["id"] for item in selected.json()["candidates"]] == [first.id]
    assert evidence.json()[0]["extractor"] == "test" and evidence.json()[0]["source_url"] == first.source_url
    assert client.get("/discovery/candidates/missing").status_code == 404
    assert client.get("/discovery/candidates/missing/evidence").status_code == 404


class FakeOrchestration:
    def __init__(self, db_session):
        self.db_session, self.calls = db_session, []

    def execute(self, run_id, top_n, minimum_score, minimum_confidence):
        self.calls.append((run_id, top_n, minimum_score, minimum_confidence))
        run = DiscoveryRunRepository(self.db_session).get_by_id(run_id)
        if run is None:
            raise ValueError("discovery run does not exist")
        return DiscoveryRunOrchestrationResult(run=run, ranked_candidate_ids=(), selected_candidate_ids=())


def test_execute_delegates_and_maps_run_state_errors(db_session, db_session_factory):
    run = create_run(db_session)
    fake = FakeOrchestration(db_session)
    client = api_client(db_session_factory, fake)
    response = client.post(f"/discovery/runs/{run.id}/execute", json={"top_n": 2, "minimum_score": 50, "minimum_evidence_confidence": 80})
    assert response.status_code == 200 and fake.calls == [(run.id, 2, 50, 80)]
    assert client.post("/discovery/runs/missing/execute", json={}).status_code == 404
    # Request validation handles invalid policy before the orchestrator dependency is called.
    assert client.post(f"/discovery/runs/{run.id}/execute", json={"top_n": 0}).status_code == 422


def test_main_registers_discovery_routes_without_starting_lifespan():
    from app.main import app
    assert any(route.path == "/discovery/runs" for route in app.routes)
