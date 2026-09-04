"""UIF5C qualification for read-only content operations visibility."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.content as content_api
from app.repositories.content_brief_repository import ContentBriefRepository
from app.repositories.content_evaluation_repository import ContentEvaluationRepository
from app.repositories.content_generation_run_repository import ContentGenerationRunRepository
from app.repositories.content_repurposing_run_repository import ContentRepurposingRunRepository
from app.repositories.generated_content_artifact_repository import GeneratedContentArtifactRepository
from app.schemas.content import ContentBriefResponse, ContentEvaluationResponse


class StubRepository:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def list_recent(self, limit=50):
        self.calls.append((self.name, limit))
        return []


def _client(monkeypatch):
    calls = []
    monkeypatch.setattr(content_api, "ContentBriefRepository", lambda db: StubRepository("briefs", calls))
    monkeypatch.setattr(content_api, "ContentGenerationRunRepository", lambda db: StubRepository("generation_runs", calls))
    monkeypatch.setattr(content_api, "GeneratedContentArtifactRepository", lambda db: StubRepository("artifacts", calls))
    monkeypatch.setattr(content_api, "ContentEvaluationRepository", lambda db: StubRepository("evaluations", calls))
    monkeypatch.setattr(content_api, "ContentRepurposingRunRepository", lambda db: StubRepository("repurposing_runs", calls))
    app = FastAPI()
    app.include_router(content_api.router)
    app.dependency_overrides[content_api.get_db] = lambda: object()
    return TestClient(app), calls


def test_operations_defaults_to_fifty_and_returns_complete_read_model(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/content/operations")
    assert response.status_code == 200
    assert response.json() == {"briefs": [], "generation_runs": [], "artifacts": [], "evaluations": [], "repurposing_runs": []}
    assert calls == [("briefs", 50), ("generation_runs", 50), ("artifacts", 50), ("evaluations", 50), ("repurposing_runs", 50)]


def test_operations_forwards_explicit_limit(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/content/operations?limit=7")
    assert response.status_code == 200
    assert calls == [("briefs", 7), ("generation_runs", 7), ("artifacts", 7), ("evaluations", 7), ("repurposing_runs", 7)]


@pytest.mark.parametrize("limit", [0, 101])
def test_operations_rejects_out_of_bounds_limit(monkeypatch, limit):
    client, calls = _client(monkeypatch)
    response = client.get(f"/content/operations?limit={limit}")
    assert response.status_code == 422
    assert calls == []


def test_content_brief_response_matches_durable_model_fields():
    now = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    row = ContentBriefResponse.model_validate({
        "id": "brief-1", "discovery_run_id": "run-1", "discovery_candidate_id": "candidate-1",
        "content_type": "review", "channel_intent": "blog", "objective": "Explain the offer",
        "audience_intent": "compare", "audience_problem": "needs hosting", "angle": "value",
        "call_to_action": "learn more", "tone": "clear", "required_disclosure": "affiliate",
        "key_benefits": ["speed"], "proof_points": ["evidence-1"], "target_keywords": ["hosting"],
        "constraints": {"no_hype": True}, "idempotency_key": "brief-key", "status": "READY",
        "created_at": now, "updated_at": now,
    })
    assert row.id == "brief-1"
    assert row.status == "READY"


def test_content_evaluation_response_matches_durable_model_fields():
    now = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
    row = ContentEvaluationResponse.model_validate({
        "id": "evaluation-1", "artifact_id": "artifact-1", "content_brief_id": "brief-1",
        "generation_run_id": "generation-1", "factual_grounding_score": 95,
        "offer_alignment_score": 90, "intent_alignment_score": 91, "clarity_score": 92,
        "cta_score": 89, "compliance_score": 100, "overall_score": 93,
        "decision": "APPROVED", "approved": True, "evaluator_version": "evaluator-v1",
        "policy_version": "policy-v1", "claim_results": [], "compliance_flags": [],
        "unsupported_claims": [], "missing_evidence_ids": [], "revision_reasons": [],
        "rejection_reasons": [], "created_at": now, "updated_at": now,
    })
    assert row.overall_score == 93
    assert row.approved is True


@pytest.mark.parametrize(
    ("repository_cls", "model_name"),
    [
        (ContentBriefRepository, "ContentBrief"),
        (ContentGenerationRunRepository, "ContentGenerationRun"),
        (GeneratedContentArtifactRepository, "GeneratedContentArtifact"),
        (ContentEvaluationRepository, "ContentEvaluation"),
        (ContentRepurposingRunRepository, "ContentRepurposingRun"),
    ],
)
def test_recent_repository_queries_are_read_only_newest_first(repository_cls, model_name):
    calls = []
    class FakeQuery:
        def order_by(self, *expressions): calls.append(("order_by", len(expressions))); return self
        def limit(self, value): calls.append(("limit", value)); return self
        def all(self): calls.append(("all",)); return ["newest", "older"]
    class FakeDb:
        def query(self, model): calls.append(("query", model.__name__)); return FakeQuery()
    repository = repository_cls(FakeDb())
    assert repository.list_recent(limit=2) == ["newest", "older"]
    assert calls == [("query", model_name), ("order_by", 2), ("limit", 2), ("all",)]
