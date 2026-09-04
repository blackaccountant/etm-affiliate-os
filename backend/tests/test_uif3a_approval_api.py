from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_db
from app.main import app
from app.optimization.economic_recommendation_approval_contracts import (
    ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
    EconomicRecommendationApprovalOutcome,
    EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
    EconomicRecommendationProposalRow,
)
from app.optimization.ordered_economic_candidate_preference_contracts import (
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION,
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS,
)

import app.api.optimization_approval_routes as route_module


WHEN = datetime(2026, 9, 4, tzinfo=timezone.utc)
DECIDED = datetime(2026, 9, 4, 1, tzinfo=timezone.utc)


def _proposal_payload(**overrides):
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


def _payload(state="APPROVED", approved_dimensions=None, **overrides):
    if approved_dimensions is None:
        approved_dimensions = [
            [{"name": "affiliate_program", "value": 7}]
        ]
    payload = {
        "proposal_request": _proposal_payload(),
        "approval_decision": {
            "decision_state": state,
            "approved_dimensions": approved_dimensions,
            "actor_reference": "human-reviewer-001",
            "decision_reference": "decision-001",
            "decided_at": "2026-09-04T01:00:00Z",
        },
        "approval_policy": {"policy_version": "approval-v1"},
    }
    payload.update(overrides)
    return payload


def _row(program_id=7, amount="123.45"):
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


def _outcome(
    state=EconomicRecommendationApprovalState.APPROVED,
    approved_rows=(),
):
    return EconomicRecommendationApprovalOutcome(
        currency="USD",
        decision_state=state,
        approved_rows=approved_rows,
        evaluated_at=WHEN,
        actor_reference="human-reviewer-001",
        decision_reference="decision-001",
        decided_at=DECIDED,
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        source_recommendation_semantics=(
            ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
        ),
        source_recommendation_contract_version=(
            ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
        ),
        approval_semantics=ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
        approval_contract_version=ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    )


class _CapturedService:
    outcome = _outcome()
    calls = 0
    request = None
    db = None

    def __init__(self, db):
        type(self).db = db

    def project(self, request):
        type(self).calls += 1
        type(self).request = request
        return type(self).outcome


@pytest.fixture(autouse=True)
def _clean_overrides(monkeypatch):
    _CapturedService.outcome = _outcome()
    _CapturedService.calls = 0
    _CapturedService.request = None
    _CapturedService.db = None

    def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    monkeypatch.setattr(
        route_module,
        "EconomicRecommendationApprovalService",
        _CapturedService,
    )
    yield
    app.dependency_overrides.clear()


def _client():
    return TestClient(app)


def test_valid_approved_request_maps_exact_frozen_m11a9_contract_once():
    response = _client().post(
        "/optimization/approvals/decide",
        json=_payload(),
    )

    assert response.status_code == 200
    assert _CapturedService.calls == 1

    request = _CapturedService.request
    candidate = request.proposal_request.preference_request.candidate_request
    policy = candidate.eligibility_policy
    decision = request.approval_decision

    assert candidate.dimensions == ("affiliate_program",)
    assert candidate.currency == "USD"
    assert candidate.evaluated_at == WHEN
    assert policy.policy_version == "eligibility-v1"
    assert policy.minimum_settled_earning_count == 1
    assert policy.minimum_settled_conversion_count == 1
    assert policy.minimum_settlement_link_count == 1
    assert policy.minimum_attribution_click_count is None
    assert policy.maximum_settlement_observation_age is None
    assert request.proposal_request.preference_request.comparison_policy.policy_version == (
        "comparison-v1"
    )
    assert request.proposal_request.recommendation_policy.policy_version == (
        "recommendation-v1"
    )
    assert decision.decision_state is EconomicRecommendationApprovalState.APPROVED
    assert decision.approved_dimensions == ((("affiliate_program", 7),),)
    assert decision.actor_reference == "human-reviewer-001"
    assert decision.decision_reference == "decision-001"
    assert decision.decided_at == DECIDED
    assert request.approval_policy.policy_version == "approval-v1"


@pytest.mark.parametrize("state", ["REJECTED", "DEFERRED"])
def test_nonapproval_states_map_explicit_empty_selection(state):
    enum_state = EconomicRecommendationApprovalState(state)
    _CapturedService.outcome = _outcome(state=enum_state)

    response = _client().post(
        "/optimization/approvals/decide",
        json=_payload(state=state, approved_dimensions=[]),
    )

    assert response.status_code == 200
    assert _CapturedService.calls == 1
    decision = _CapturedService.request.approval_decision
    assert decision.decision_state is enum_state
    assert decision.approved_dimensions == ()
    assert response.json()["decision_state"] == state
    assert response.json()["approved_rows"] == []


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p["approval_decision"].pop("approved_dimensions"),
        lambda p: p["approval_decision"].update({"actor_reference": " "}),
        lambda p: p["approval_decision"].update({"decision_reference": " "}),
        lambda p: p["approval_decision"].update(
            {"decided_at": "2026-09-04T02:00:00+01:00"}
        ),
        lambda p: p["approval_decision"].update({"decision_state": "PENDING"}),
        lambda p: p["approval_decision"]["approved_dimensions"][0][0].update(
            {"value": True}
        ),
        lambda p: p.update({"unexpected": True}),
    ],
)
def test_strict_http_validation_returns_422_without_service(mutator):
    payload = _payload()
    mutator(payload)

    response = _client().post(
        "/optimization/approvals/decide",
        json=payload,
    )

    assert response.status_code == 422
    assert _CapturedService.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        _payload(state="APPROVED", approved_dimensions=[]),
        _payload(
            state="REJECTED",
            approved_dimensions=[
                [{"name": "affiliate_program", "value": 7}]
            ],
        ),
    ],
)
def test_frozen_state_selection_contradictions_are_safe_422(payload):
    response = _client().post(
        "/optimization/approvals/decide",
        json=deepcopy(payload),
    )

    assert response.status_code == 422
    assert "frozen contract" in response.json()["detail"]
    assert _CapturedService.calls == 0


def test_proposal_domain_normalization_failure_is_safe_422():
    payload = _payload()
    payload["proposal_request"]["dimensions"] = [
        "affiliate_program",
        "affiliate_program",
    ]

    response = _client().post(
        "/optimization/approvals/decide",
        json=payload,
    )

    assert response.status_code == 422
    assert "frozen contract" in response.json()["detail"]
    assert _CapturedService.calls == 0


def test_outcome_serializes_exact_13_field_m11a9_transport_and_a8_row():
    _CapturedService.outcome = _outcome(approved_rows=(_row(),))

    response = _client().post(
        "/optimization/approvals/decide",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == [
        "currency",
        "decision_state",
        "approved_rows",
        "evaluated_at",
        "actor_reference",
        "decision_reference",
        "decided_at",
        "recommendation_policy_version",
        "approval_policy_version",
        "source_recommendation_semantics",
        "source_recommendation_contract_version",
        "approval_semantics",
        "approval_contract_version",
    ]
    assert body["currency"] == "USD"
    assert body["decision_state"] == "APPROVED"
    assert body["evaluated_at"] == "2026-09-04T00:00:00+00:00"
    assert body["decided_at"] == "2026-09-04T01:00:00+00:00"
    assert body["actor_reference"] == "human-reviewer-001"
    assert body["decision_reference"] == "decision-001"
    assert body["approval_semantics"] == ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS
    assert body["approval_contract_version"] == (
        ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
    )

    assert len(body["approved_rows"]) == 1
    row = body["approved_rows"][0]
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
    assert row["dimensions"] == [
        {"name": "affiliate_program", "value": 7}
    ]
    assert row["operating_profit"] == "123.45"
    assert isinstance(row["operating_profit"], str)
    assert row["recommendation_proposal_contract_version"] == (
        ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
    )

    forbidden = {
        "budget",
        "allocation",
        "traffic",
        "experiment",
        "execution",
        "launch",
        "action",
        "dispatch",
    }
    assert forbidden.isdisjoint(body.keys())
    assert forbidden.isdisjoint(row.keys())


def test_frozen_service_contradiction_is_safe_400_without_internal_detail(monkeypatch):
    class RejectingService(_CapturedService):
        def project(self, request):
            type(self).calls += 1
            raise ValueError("sensitive SQL contradiction")

    monkeypatch.setattr(
        route_module,
        "EconomicRecommendationApprovalService",
        RejectingService,
    )

    response = _client().post(
        "/optimization/approvals/decide",
        json=_payload(),
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "sensitive" not in detail
    assert "SQL" not in detail
    assert "frozen optimization contract" in detail
