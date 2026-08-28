from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.discovery import router
from app.dependencies import get_db, get_discovery_run_orchestration_service
from app.discovery.contracts import CandidateDisposition, CommissionModel, DiscoveryCandidateCreate, DiscoveryInputType, DiscoveryRunCreate, DiscoveryRunStatus, EvidenceObservationCreate, VerificationStatus
from app.models.affiliate_program import AffiliateProgram
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation
from app.models.product import Product
from app.repositories.discovery_candidate_repository import DiscoveryCandidateRepository
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.evidence_observation_repository import EvidenceObservationRepository
from app.schemas.discovery import DiscoveryCandidateResponse, DiscoveryRunResponse, EvidenceObservationResponse
from app.services.discovery_candidate_scoring_service import DiscoveryRankingService
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService


@pytest.fixture(autouse=True)
def isolation_sentinels(monkeypatch):
    """Focused API tests must only use the overridden SQLite session and fake seams."""
    def fail_default_session():
        raise AssertionError("configured SessionLocal must not be used by focused discovery API tests")

    def fail_network(*args, **kwargs):
        raise AssertionError("focused discovery API tests must not use network access")

    # get_db resolves this import alias, so this guards the production dependency path.
    monkeypatch.setattr("app.dependencies.SessionLocal", fail_default_session)
    monkeypatch.setattr(httpx, "get", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch", fail_network)
    monkeypatch.setattr("app.services.website_fetcher.WebsiteFetcher.fetch_with_metadata", fail_network)


def api_client(db_session_factory, orchestration=None, raise_server_exceptions=True):
    app = FastAPI()
    app.include_router(router, prefix="/discovery")

    def override_db():
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    if orchestration is not None:
        app.dependency_overrides[get_discovery_run_orchestration_service] = lambda: orchestration
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def create_run(db_session, key=None, status=DiscoveryRunStatus.CREATED, input_type=DiscoveryInputType.URL, input_data=None):
    record = DiscoveryRunRepository(db_session).create(DiscoveryRunCreate(
        input_type=input_type,
        input_value="https://acme.example",
        input_data=input_data,
        idempotency_key=key,
    ))
    if status is not DiscoveryRunStatus.CREATED:
        record = DiscoveryRunRepository(db_session).update_status(record.id, status)
    return record


def create_candidate(db_session, run, name, *, selected=False, partial=False, score=60, **overrides):
    values = {
        "source_adapter": "official_site", "source_type": "official_site", "source_url": f"https://acme.example/{name}",
        "vendor_name": "Acme", "canonical_domain": "acme.example", "program_name": f"Program {name}",
        "affiliate_network": "Acme Network", "affiliate_url": f"https://acme.example/{name}/apply",
        "program_identity_key": f"program:{name}", "dedupe_key": f"candidate:{name}",
        "commission_model": CommissionModel.PERCENT, "commission_percent": Decimal("30"),
        "commission_amount": Decimal("12.50"), "commission_currency": "usd", "recurring_period": "monthly",
        "cookie_days": 90, "payout_threshold": Decimal("100.00"), "payout_currency": "usd",
        "verification_status": VerificationStatus.PARTIAL if partial else VerificationStatus.VERIFIED,
        "disposition": CandidateDisposition.SELECTED if selected else CandidateDisposition.VERIFIED,
        "confidence": 80, "score": score,
        "score_breakdown": {"basis": "affiliate_economics_only", "score": score},
        "score_reasons": [{"title": "test", "points": 1}],
    }
    values.update(overrides)
    return DiscoveryCandidateRepository(db_session).create(run.id, DiscoveryCandidateCreate(**values))


def create_evidence(db_session, candidate, suffix="one", **overrides):
    values = {
        "candidate_id": candidate.id, "claim_type": f"commission_percent_{suffix}",
        "observed_value": {"rate": 30, "source": suffix}, "source_url": f"{candidate.source_url}#{suffix}",
        "source_type": "official_site", "excerpt": f"Earn 30%, evidence {suffix}.", "http_status": 200,
        "content_hash": f"hash-{suffix}", "extractor": "official-site-parser", "extractor_version": "2026.08", "confidence": 90,
    }
    values.update(overrides)
    return EvidenceObservationRepository(db_session).create(EvidenceObservationCreate(**values))


def durable_snapshot(db_session, run_id):
    db_session.expire_all()
    run = db_session.get(DiscoveryRun, run_id)
    candidates = db_session.query(DiscoveryCandidate).filter_by(run_id=run_id).order_by(DiscoveryCandidate.id).all()
    candidate_ids = [item.id for item in candidates]
    evidence_count = db_session.query(EvidenceObservation).filter(EvidenceObservation.candidate_id.in_(candidate_ids)).count() if candidate_ids else 0
    return {
        "run": (run.status, run.candidate_count, run.verified_count, run.selected_count, run.updated_at),
        "candidates": [(item.id, item.disposition, item.score, item.updated_at) for item in candidates],
        "candidate_count": len(candidates), "evidence_count": evidence_count,
    }


def assert_response_keys(payload, model):
    assert set(payload) == set(model.model_fields)
    assert "_sa_instance_state" not in payload


def test_create_idempotency_input_data_and_run_read_contract(db_session, db_session_factory):
    client = api_client(db_session_factory)
    input_data = {"market": "creator tools", "filters": ["verified", {"min_score": 70}]}
    payload = {"input_type": "URL", "input_value": "https://acme.example", "input_data": input_data, "idempotency_key": "api-key"}
    first = client.post("/discovery/runs", json=payload)
    second = client.post("/discovery/runs", json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"] and first.json()["input_data"] == input_data
    assert first.json()["created_at"].endswith(("+00:00", "Z"))
    assert db_session.query(DiscoveryRun).filter_by(idempotency_key="api-key").count() == 1
    read = client.get(f"/discovery/runs/{first.json()['id']}")
    assert read.status_code == 200 and read.json()["input_data"] == input_data
    assert_response_keys(read.json(), DiscoveryRunResponse)
    assert db_session.query(Product).count() == 0 and db_session.query(AffiliateProgram).count() == 0
    assert client.get("/discovery/runs/missing").status_code == 404
    assert client.post("/discovery/runs", json={"input_type": "URL", "input_value": ""}).status_code == 422


def test_candidate_responses_preserve_complete_typed_and_unknown_economics(db_session, db_session_factory):
    run = create_run(db_session)
    complete = create_candidate(db_session, run, "complete", selected=True, score=88)
    unknown = create_candidate(db_session, run, "unknown", partial=True, commission_model=CommissionModel.UNKNOWN, commission_percent=None, commission_amount=None, commission_currency=None, recurring_period=None, cookie_days=None, payout_threshold=None, payout_currency=None, confidence=None, score=None, score_breakdown=None, score_reasons=None)
    client = api_client(db_session_factory)
    listed = client.get(f"/discovery/runs/{run.id}/candidates")
    single = client.get(f"/discovery/candidates/{complete.id}")
    assert listed.status_code == single.status_code == 200
    payload = single.json()
    assert payload["commission_model"] == "PERCENT" and payload["commission_percent"] == "30.00"
    assert payload["commission_amount"] == "12.50" and payload["commission_currency"] == "USD"
    assert payload["recurring_period"] == "monthly" and payload["cookie_days"] == 90
    assert payload["payout_threshold"] == "100.00" and payload["payout_currency"] == "USD"
    assert payload["verification_status"] == "VERIFIED" and payload["disposition"] == "SELECTED"
    assert payload["confidence"] == 80 and payload["score"] == 88
    assert payload["score_breakdown"] == {"basis": "affiliate_economics_only", "score": 88}
    assert payload["score_reasons"] == [{"title": "test", "points": 1}]
    assert_response_keys(payload, DiscoveryCandidateResponse)
    unknown_payload = next(item for item in listed.json() if item["id"] == unknown.id)
    for field in ("commission_percent", "commission_amount", "commission_currency", "recurring_period", "cookie_days", "payout_threshold", "payout_currency", "confidence", "score", "score_breakdown", "score_reasons"):
        assert unknown_payload[field] is None
    assert client.get("/discovery/runs/missing/candidates").status_code == 404
    assert client.get("/discovery/candidates/missing").status_code == 404


def test_ranking_matches_service_is_deterministic_and_read_only(db_session, db_session_factory):
    run = create_run(db_session)
    verified = create_candidate(db_session, run, "verified", selected=True, score=10)
    partial = create_candidate(db_session, run, "partial", partial=True, score=99)
    create_evidence(db_session, verified, "verified")
    create_evidence(db_session, partial, "partial-one")
    create_evidence(db_session, partial, "partial-two")
    DiscoveryRunRepository(db_session).update_counters(run.id, candidate_count=2, verified_count=1, selected_count=1)
    expected_ids = [item.candidate.id for item in DiscoveryRankingService(db_session).rank(run.id)]
    before = durable_snapshot(db_session, run.id)
    client = api_client(db_session_factory)
    first, second = client.get(f"/discovery/runs/{run.id}/ranking"), client.get(f"/discovery/runs/{run.id}/ranking")
    assert first.status_code == second.status_code == 200
    assert [item["candidate"]["id"] for item in first.json()["items"]] == expected_ids == [verified.id, partial.id]
    assert [item["rank"] for item in first.json()["items"]] == [1, 2]
    assert [item["evidence_count"] for item in first.json()["items"]] == [1, 2]
    assert first.json() == second.json() and durable_snapshot(db_session, run.id) == before


def test_selected_and_all_get_endpoints_are_deterministic_and_read_only(db_session, db_session_factory):
    run = create_run(db_session)
    selected = create_candidate(db_session, run, "alpha", selected=True, score=70)
    unselected = create_candidate(db_session, run, "zeta", partial=True, score=99)
    create_evidence(db_session, selected, "first")
    create_evidence(db_session, selected, "second")
    DiscoveryRunRepository(db_session).update_counters(run.id, candidate_count=2, verified_count=1, selected_count=1)
    client = api_client(db_session_factory)
    paths = [f"/discovery/runs/{run.id}", f"/discovery/runs/{run.id}/candidates", f"/discovery/runs/{run.id}/ranking", f"/discovery/runs/{run.id}/selected", f"/discovery/candidates/{selected.id}", f"/discovery/candidates/{selected.id}/evidence"]
    before = durable_snapshot(db_session, run.id)
    results = {path: [client.get(path), client.get(path)] for path in paths}
    assert all(response.status_code == 200 for pair in results.values() for response in pair)
    assert all(pair[0].json() == pair[1].json() for pair in results.values())
    selected_payload = results[f"/discovery/runs/{run.id}/selected"][0].json()["candidates"]
    assert [item["id"] for item in selected_payload] == [selected.id]
    assert len(selected_payload) == db_session.get(DiscoveryRun, run.id).selected_count
    assert unselected.id not in [item["id"] for item in selected_payload]
    assert durable_snapshot(db_session, run.id) == before


def test_evidence_response_completeness_and_ordering(db_session, db_session_factory):
    run = create_run(db_session)
    candidate = create_candidate(db_session, run, "evidence")
    first = create_evidence(db_session, candidate, "one", observed_value={"rate": 30}, http_status=201, confidence=91)
    second = create_evidence(db_session, candidate, "two", observed_value={"rate": 35}, http_status=202, confidence=92)
    client = api_client(db_session_factory)
    one, two = client.get(f"/discovery/candidates/{candidate.id}/evidence"), client.get(f"/discovery/candidates/{candidate.id}/evidence")
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert [item["id"] for item in one.json()] == [first.id, second.id]
    payload = one.json()[0]
    assert payload["observed_value"] == {"rate": 30} and payload["source_url"] == f"{candidate.source_url}#one"
    assert payload["source_type"] == "official_site" and payload["excerpt"] == "Earn 30%, evidence one."
    assert payload["http_status"] == 201 and payload["content_hash"] == "hash-one"
    assert payload["extractor"] == "official-site-parser" and payload["extractor_version"] == "2026.08"
    assert payload["confidence"] == 91 and payload["observed_at"].endswith(("+00:00", "Z")) and payload["created_at"].endswith(("+00:00", "Z"))
    assert_response_keys(payload, EvidenceObservationResponse)
    assert client.get("/discovery/candidates/missing/evidence").status_code == 404


class CountingIngestion:
    def __init__(self):
        self.calls = 0

    def ingest(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("completed execution must not rediscover")


class UnexpectedFailureOrchestration:
    def execute(self, *args, **kwargs):
        raise RuntimeError("database transport unavailable")


def test_execute_completed_is_idempotent_and_durable(db_session, db_session_factory):
    run = create_run(db_session, status=DiscoveryRunStatus.COMPLETED)
    selected = create_candidate(db_session, run, "winner", selected=True, score=80)
    other = create_candidate(db_session, run, "other", partial=True, score=99)
    create_evidence(db_session, selected)
    DiscoveryRunRepository(db_session).update_counters(run.id, candidate_count=2, verified_count=1, selected_count=1)
    ingestion = CountingIngestion()
    before = durable_snapshot(db_session, run.id)
    client = api_client(db_session_factory, DiscoveryRunOrchestrationService(db_session, ingestion=ingestion))
    first, second = client.post(f"/discovery/runs/{run.id}/execute", json={}), client.post(f"/discovery/runs/{run.id}/execute", json={})
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert first.json()["run"]["id"] == run.id and first.json()["ranked_candidate_ids"] == [selected.id, other.id]
    assert first.json()["selected_candidate_ids"] == [selected.id] and ingestion.calls == 0
    assert durable_snapshot(db_session, run.id) == before
    assert db_session.query(Product).count() == 0 and db_session.query(AffiliateProgram).count() == 0


def test_execute_status_and_unsupported_http_outcomes(db_session, db_session_factory):
    running, failed = create_run(db_session, status=DiscoveryRunStatus.RUNNING), create_run(db_session, status=DiscoveryRunStatus.FAILED)
    client = api_client(db_session_factory, DiscoveryRunOrchestrationService(db_session, ingestion=CountingIngestion()))
    assert client.post(f"/discovery/runs/{running.id}/execute", json={}).status_code == 409
    assert client.post(f"/discovery/runs/{failed.id}/execute", json={}).status_code == 409
    for input_type in (DiscoveryInputType.MARKET, DiscoveryInputType.NICHE, DiscoveryInputType.SEED):
        run = create_run(db_session, input_type=input_type)
        assert client.post(f"/discovery/runs/{run.id}/execute", json={}).status_code == 400
        assert db_session.get(DiscoveryRun, run.id).status == DiscoveryRunStatus.FAILED.value
    assert client.post("/discovery/runs/missing/execute", json={}).status_code == 404
    assert client.post(f"/discovery/runs/{running.id}/execute", json={"top_n": 0}).status_code == 422


def test_execute_unexpected_failure_is_not_reported_as_success(db_session, db_session_factory):
    run = create_run(db_session)
    client = api_client(db_session_factory, UnexpectedFailureOrchestration(), raise_server_exceptions=False)
    response = client.post(f"/discovery/runs/{run.id}/execute", json={})
    assert response.status_code == 500 and not 200 <= response.status_code < 300


def test_main_openapi_registers_each_discovery_operation_once_without_lifespan():
    from app.main import app

    expected = {("/discovery/runs", "POST"), ("/discovery/runs/{run_id}/execute", "POST"), ("/discovery/runs/{run_id}", "GET"), ("/discovery/runs/{run_id}/candidates", "GET"), ("/discovery/runs/{run_id}/ranking", "GET"), ("/discovery/runs/{run_id}/selected", "GET"), ("/discovery/candidates/{candidate_id}", "GET"), ("/discovery/candidates/{candidate_id}/evidence", "GET")}
    actual = [(route.path, method) for route in app.routes for method in getattr(route, "methods", set()) if (route.path, method) in expected]
    assert set(actual) == expected and len(actual) == len(expected)
    schema = app.openapi()
    assert {(path, method.upper()) for path, item in schema["paths"].items() for method in item if (path, method.upper()) in expected} == expected
