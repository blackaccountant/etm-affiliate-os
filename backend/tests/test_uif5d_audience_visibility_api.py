"""UIF5D qualification for read-only audience intelligence visibility."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.audience_visibility_routes as audience_api
from app.api.audience_visibility_schemas import (
    AudienceProfileVisibilityResponse,
    AudienceQualificationVisibilityResponse,
)
from app.repositories.audience_visibility_repository import AudienceVisibilityRepository
from app.services.audience_visibility_service import AudienceVisibilityService


EMPTY_SNAPSHOT = {
    "profiles": [],
    "signals": [],
    "qualifications": [],
    "segments": [],
    "segment_revisions": [],
    "memberships": [],
}


class StubService:
    def __init__(self, calls):
        self.calls = calls

    def snapshot(self, limit=50):
        self.calls.append(limit)
        return dict(EMPTY_SNAPSHOT)


def _client(monkeypatch):
    calls = []
    monkeypatch.setattr(
        audience_api,
        "AudienceVisibilityService",
        lambda repository: StubService(calls),
    )
    app = FastAPI()
    app.include_router(audience_api.router)
    app.dependency_overrides[audience_api.get_db] = lambda: object()
    return TestClient(app), calls


def test_visibility_defaults_to_fifty_and_returns_complete_snapshot(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/audience/visibility")
    assert response.status_code == 200
    assert response.json() == EMPTY_SNAPSHOT
    assert calls == [50]


def test_visibility_forwards_explicit_limit(monkeypatch):
    client, calls = _client(monkeypatch)
    response = client.get("/audience/visibility?limit=7")
    assert response.status_code == 200
    assert calls == [7]


@pytest.mark.parametrize("limit", [0, 101])
def test_visibility_rejects_out_of_bounds_limit_before_service(monkeypatch, limit):
    client, calls = _client(monkeypatch)
    response = client.get(f"/audience/visibility?limit={limit}")
    assert response.status_code == 422
    assert calls == []


def test_service_reads_each_visibility_collection_exactly_once():
    calls = []

    class StubRepository:
        def __getattr__(self, name):
            if not name.startswith("list_"):
                raise AttributeError(name)
            def read(limit):
                calls.append((name, limit))
                return [name]
            return read

    snapshot = AudienceVisibilityService(StubRepository()).snapshot(9)
    assert snapshot == {
        "profiles": ["list_profiles"],
        "signals": ["list_signals"],
        "qualifications": ["list_qualifications"],
        "segments": ["list_segments"],
        "segment_revisions": ["list_segment_revisions"],
        "memberships": ["list_memberships"],
    }
    assert calls == [
        ("list_profiles", 9),
        ("list_signals", 9),
        ("list_qualifications", 9),
        ("list_segments", 9),
        ("list_segment_revisions", 9),
        ("list_memberships", 9),
    ]


def test_profile_schema_exposes_pseudonymous_intelligence_not_external_identity():
    now = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)
    row = AudienceProfileVisibilityResponse.model_validate({
        "id": "profile-1",
        "subject_id": "subject-1",
        "profile_ruleset_version": "profile-v1",
        "source_fingerprint": "a" * 64,
        "derived_at": now,
        "effective_as_of": now,
        "last_signal_observed_at": now,
        "summary_json": {"topics": ["hosting"]},
    })
    assert row.subject_id == "subject-1"
    assert not hasattr(row, "normalized_reference")
    assert not hasattr(row, "source_namespace")


def test_qualification_schema_preserves_recorded_scores_and_status():
    now = datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc)
    row = AudienceQualificationVisibilityResponse.model_validate({
        "id": "assessment-1",
        "profile_id": "profile-1",
        "scoring_ruleset_version": "qualification-v1",
        "context_type": "PRODUCT",
        "problem_strength": 80,
        "interest_alignment": 81,
        "research_intent": 82,
        "comparison_intent": 83,
        "evaluation_intent": 84,
        "pricing_intent": 85,
        "purchase_request_intent": 86,
        "purchase_signal": 87,
        "engagement": 88,
        "business_need_fit": 89,
        "intent_score": 90,
        "qualification_score": 91,
        "qualification_status": "HIGH_INTENT",
        "derived_at": now,
    })
    assert row.intent_score == 90
    assert row.qualification_score == 91
    assert row.qualification_status == "HIGH_INTENT"


@pytest.mark.parametrize(
    ("method_name", "model_name"),
    [
        ("list_profiles", "AudienceProfile"),
        ("list_signals", "AudienceSignal"),
        ("list_qualifications", "AudienceQualificationAssessment"),
        ("list_segments", "AudienceSegment"),
        ("list_segment_revisions", "AudienceSegmentRevision"),
        ("list_memberships", "AudienceSegmentMembership"),
    ],
)
def test_visibility_repository_queries_are_read_only_newest_first(method_name, model_name):
    calls = []

    class FakeQuery:
        def order_by(self, *expressions):
            calls.append(("order_by", len(expressions)))
            return self
        def limit(self, value):
            calls.append(("limit", value))
            return self
        def all(self):
            calls.append(("all",))
            return ["newest", "older"]

    class FakeDb:
        def query(self, model):
            calls.append(("query", model.__name__))
            return FakeQuery()

    repository = AudienceVisibilityRepository(FakeDb())
    assert getattr(repository, method_name)(2) == ["newest", "older"]
    assert calls == [
        ("query", model_name),
        ("order_by", 2),
        ("limit", 2),
        ("all",),
    ]
