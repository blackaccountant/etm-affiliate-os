from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_db
from app.main import app
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
    EconomicRecommendationProposalRow,
)
from app.optimization.ordered_economic_candidate_preference_contracts import (
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION,
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS,
)

import app.api.optimization_recommendation_routes as route_module


WHEN = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _payload(**overrides):
    payload = {
        "dimensions": ["affiliate_program"],
        "currency": "USD",
        "evaluated_at": "2026-09-04T00:00:00Z",
        "eligibility_policy": {
            "policy_version": "eligibility-v1",
            "minimum_settled_earning_count": 1,
            "minimum_settled_conversion_count": 1,
            "minimum_settlement_link_count": 1,
            "minimum_attribution_click_count": None,
            "maximum_settlement_observation_age": None,
        },
        "comparison_policy_version": "comparison-v1",
        "recommendation_policy_version": "recommendation-v1",
    }
    payload.update(overrides)
    return payload


def _row(program_id=1, amount="123.45"):
    return EconomicRecommendationProposalRow(
        currency="USD",
        dimensions=(("affiliate_program", program_id),),
        operating_profit=Decimal(amount),
        preference_tier=1,
        evaluated_at=WHEN,
        eligibility_policy_version="eligibility-v1",
        eligibility_policy_fingerprint="fingerprint",
        comparison_policy_version="comparison-v1",
        recommendation_policy_version="recommendation-v1",
        source_ordered_preference_semantics=(
            ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS
        ),
        source_ordered_preference_contract_version=(
            ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION
        ),
        recommendation_proposal_semantics=(
            ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
        ),
        recommendation_proposal_contract_version=(
            ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
        ),
    )


class _CapturedService:
    rows = ()
    calls = 0
    request = None
    db = None

    def __init__(self, db):
        type(self).db = db

    def project(self, request):
        type(self).calls += 1
        type(self).request = request
        return type(self).rows


@pytest.fixture(autouse=True)
def _clean_overrides(monkeypatch):
    _CapturedService.rows = ()
    _CapturedService.calls = 0
    _CapturedService.request = None
    _CapturedService.db = None

    def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    monkeypatch.setattr(
        route_module,
        "EconomicRecommendationProposalService",
        _CapturedService,
    )
    yield
    app.dependency_overrides.clear()


def _client(api_auth_headers):
    return TestClient(app, headers=api_auth_headers["operator"])


def test_route_exists_and_valid_request_maps_exact_frozen_contract(api_auth_headers):
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=_payload(),
    )
    assert response.status_code == 200
    assert response.json() == {"recommendations": []}
    assert _CapturedService.calls == 1

    request = _CapturedService.request
    candidate = request.preference_request.candidate_request
    policy = candidate.eligibility_policy

    assert candidate.dimensions == ("affiliate_program",)
    assert candidate.currency == "USD"
    assert candidate.evaluated_at == WHEN
    assert policy.policy_version == "eligibility-v1"
    assert policy.minimum_settled_earning_count == 1
    assert policy.minimum_settled_conversion_count == 1
    assert policy.minimum_settlement_link_count == 1
    assert policy.minimum_attribution_click_count is None
    assert policy.maximum_settlement_observation_age is None
    assert request.preference_request.comparison_policy.policy_version == (
        "comparison-v1"
    )
    assert request.recommendation_policy.policy_version == "recommendation-v1"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p["eligibility_policy"].pop("minimum_attribution_click_count"),
        lambda p: p["eligibility_policy"].pop("maximum_settlement_observation_age"),
        lambda p: p["eligibility_policy"].update(
            {"minimum_settled_earning_count": -1}
        ),
        lambda p: p.update({"evaluated_at": "2026-09-04T01:00:00+01:00"}),
        lambda p: p.update({"unexpected": True}),
    ],
)
def test_strict_http_validation_returns_422(mutator, api_auth_headers):
    payload = _payload()
    mutator(payload)
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=payload,
    )
    assert response.status_code == 422
    assert _CapturedService.calls == 0


def test_one_row_serializes_complete_13_field_m11a8_provenance(api_auth_headers):
    _CapturedService.rows = (_row(),)
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=_payload(),
    )
    assert response.status_code == 200

    body = response.json()
    assert len(body["recommendations"]) == 1
    row = body["recommendations"][0]

    assert list(row.keys()) == [
        "currency",
        "dimensions",
        "operating_profit",
        "preference_tier",
        "evaluated_at",
        "eligibility_policy_version",
        "eligibility_policy_fingerprint",
        "comparison_policy_version",
        "recommendation_policy_version",
        "source_ordered_preference_semantics",
        "source_ordered_preference_contract_version",
        "recommendation_proposal_semantics",
        "recommendation_proposal_contract_version",
    ]
    assert row["currency"] == "USD"
    assert row["dimensions"] == [
        {"name": "affiliate_program", "value": 1}
    ]
    assert row["operating_profit"] == "123.45"
    assert isinstance(row["operating_profit"], str)
    assert row["preference_tier"] == 1
    assert row["evaluated_at"] == "2026-09-04T00:00:00+00:00"
    assert row["recommendation_proposal_semantics"] == (
        ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
    )
    assert row["recommendation_proposal_contract_version"] == (
        ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
    )

    forbidden = {
        "winner",
        "preferred",
        "approved",
        "approval",
        "budget",
        "allocation",
        "traffic",
        "experiment",
        "execution",
    }
    assert forbidden.isdisjoint(row.keys())


def test_exact_ties_preserve_every_row_and_source_order(api_auth_headers):
    _CapturedService.rows = (
        _row(7, "500.00"),
        _row(9, "500.00"),
    )
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=_payload(),
    )
    assert response.status_code == 200
    rows = response.json()["recommendations"]
    assert [item["dimensions"][0]["value"] for item in rows] == [7, 9]
    assert [item["operating_profit"] for item in rows] == [
        "500.00",
        "500.00",
    ]
    assert _CapturedService.calls == 1


def test_domain_normalization_failure_is_safe_422(api_auth_headers):
    payload = _payload(dimensions=["affiliate_program", "affiliate_program"])
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=payload,
    )
    assert response.status_code == 422
    assert "frozen contract" in response.json()["detail"]
    assert _CapturedService.calls == 0


def test_frozen_service_contradiction_is_safe_400(monkeypatch, api_auth_headers):
    class RejectingService(_CapturedService):
        def project(self, request):
            type(self).calls += 1
            raise ValueError("sensitive internal contradiction")

    monkeypatch.setattr(
        route_module,
        "EconomicRecommendationProposalService",
        RejectingService,
    )
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=_payload(),
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "sensitive" not in detail
    assert "SQL" not in detail
    assert "frozen optimization contract" in detail


def test_duration_may_be_explicit_null_or_nonnegative_value(api_auth_headers):
    payload = _payload()
    payload["eligibility_policy"]["maximum_settlement_observation_age"] = "P7D"
    response = _client(api_auth_headers).post(
        "/optimization/recommendations/project",
        json=payload,
    )
    assert response.status_code == 200
    policy = (
        _CapturedService.request.preference_request.candidate_request
        .eligibility_policy
    )
    assert policy.maximum_settlement_observation_age == timedelta(days=7)
