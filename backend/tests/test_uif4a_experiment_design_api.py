from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_db
from app.main import app
from app.optimization.economic_recommendation_approval_contracts import (
    ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
    EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS,
    EconomicRecommendationExperimentDesignRow,
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

import app.api.optimization_experiment_design_routes as route_module


WHEN = datetime(2026, 9, 4, tzinfo=timezone.utc)
DECIDED = datetime(2026, 9, 4, 1, tzinfo=timezone.utc)
DESIGNED = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)


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


def _approval_payload(
    state="APPROVED",
    approved_dimensions=None,
    **overrides,
):
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


def _design_payload(program_id=7, reference="experiment-001"):
    return {
        "experiment_reference": reference,
        "approved_dimensions": [
            {"name": "affiliate_program", "value": program_id}
        ],
        "hypothesis": "Treatment improves the declared success measure.",
        "control_definition": "Existing strategy",
        "treatment_definition": "Approved recommendation treatment",
        "success_measure": "Operating-profit evidence",
        "observation_window": "P14D",
        "design_reference": f"design-{reference}",
        "designed_at": "2026-09-04T02:00:00Z",
    }


def _payload(
    state="APPROVED",
    approved_dimensions=None,
    designs=None,
):
    if state != "APPROVED" and approved_dimensions is None:
        approved_dimensions = []
    if designs is None:
        designs = [] if state != "APPROVED" else [_design_payload()]
    return {
        "approval_request": _approval_payload(
            state=state,
            approved_dimensions=approved_dimensions,
        ),
        "experiment_design_inputs": designs,
        "experiment_design_policy": {
            "policy_version": "experiment-design-v1",
        },
    }


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


def _design_row(program_id=7):
    return EconomicRecommendationExperimentDesignRow(
        experiment_reference="experiment-001",
        approved_recommendation_row=_row(program_id),
        hypothesis="Treatment improves the declared success measure.",
        control_definition="Existing strategy",
        treatment_definition="Approved recommendation treatment",
        success_measure="Operating-profit evidence",
        observation_window=timedelta(days=14),
        actor_reference="human-reviewer-001",
        decision_reference="decision-001",
        decided_at=DECIDED,
        design_reference="design-experiment-001",
        designed_at=DESIGNED,
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        experiment_design_policy_version="experiment-design-v1",
        source_approval_semantics=ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
        source_approval_contract_version=(
            ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
        ),
        experiment_design_semantics=(
            ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
        ),
        experiment_design_contract_version=(
            ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
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
        "EconomicRecommendationExperimentDesignService",
        _CapturedService,
    )
    yield
    app.dependency_overrides.clear()


def _client(api_auth_headers):
    return TestClient(app, headers=api_auth_headers["operator"])


def test_valid_request_maps_exact_frozen_m11a10_contract_once(api_auth_headers):
    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=_payload(),
    )

    assert response.status_code == 200
    assert _CapturedService.calls == 1

    request = _CapturedService.request
    approval = request.approval_request
    candidate = approval.proposal_request.preference_request.candidate_request
    decision = approval.approval_decision
    design = request.experiment_design_inputs[0]

    assert candidate.dimensions == ("affiliate_program",)
    assert candidate.currency == "USD"
    assert candidate.evaluated_at == WHEN
    assert decision.decision_state is EconomicRecommendationApprovalState.APPROVED
    assert decision.approved_dimensions == ((("affiliate_program", 7),),)
    assert decision.actor_reference == "human-reviewer-001"
    assert decision.decision_reference == "decision-001"
    assert decision.decided_at == DECIDED
    assert approval.approval_policy.policy_version == "approval-v1"

    assert request.experiment_design_inputs == (design,)
    assert design.experiment_reference == "experiment-001"
    assert design.approved_dimensions == (("affiliate_program", 7),)
    assert design.hypothesis == "Treatment improves the declared success measure."
    assert design.control_definition == "Existing strategy"
    assert design.treatment_definition == "Approved recommendation treatment"
    assert design.success_measure == "Operating-profit evidence"
    assert design.observation_window == timedelta(days=14)
    assert design.design_reference == "design-experiment-001"
    assert design.designed_at == DESIGNED
    assert request.experiment_design_policy.policy_version == "experiment-design-v1"


def test_approved_request_can_explicitly_project_zero_designs(api_auth_headers):
    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=_payload(designs=[]),
    )
    assert response.status_code == 200
    assert _CapturedService.calls == 1
    assert _CapturedService.request.experiment_design_inputs == ()
    assert response.json() == {"experiment_designs": []}


@pytest.mark.parametrize("state", ["REJECTED", "DEFERRED"])
def test_nonapproval_states_with_no_designs_remain_explicit_and_empty(state, api_auth_headers):
    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=_payload(state=state),
    )
    assert response.status_code == 200
    assert _CapturedService.calls == 1
    assert (
        _CapturedService.request.approval_request.approval_decision.decision_state.value
        == state
    )
    assert _CapturedService.request.experiment_design_inputs == ()
    assert response.json() == {"experiment_designs": []}


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update({"unexpected": True}),
        lambda p: p["experiment_design_inputs"][0].update({"hypothesis": " "}),
        lambda p: p["experiment_design_inputs"][0].update(
            {"observation_window": "PT0S"}
        ),
        lambda p: p["experiment_design_inputs"][0].update(
            {"observation_window": 1209600}
        ),
        lambda p: p["experiment_design_inputs"][0].update(
            {"designed_at": "2026-09-04T03:00:00+01:00"}
        ),
        lambda p: p["experiment_design_inputs"][0]["approved_dimensions"][0].update(
            {"value": True}
        ),
        lambda p: p["experiment_design_policy"].update({"policy_version": " "}),
        lambda p: p.pop("experiment_design_inputs"),
    ],
)
def test_strict_http_validation_returns_422_without_service(mutator, api_auth_headers):
    payload = _payload()
    mutator(payload)

    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=payload,
    )

    assert response.status_code == 422
    assert _CapturedService.calls == 0


def test_nested_approval_contract_contradiction_is_safe_422_before_service(api_auth_headers):
    payload = _payload(designs=[])
    payload["approval_request"]["approval_decision"]["approved_dimensions"] = []

    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=payload,
    )

    assert response.status_code == 422
    assert "frozen contract" in response.json()["detail"]
    assert _CapturedService.calls == 0


def test_frozen_service_contradiction_is_safe_400_without_internal_detail(monkeypatch, api_auth_headers):
    class RejectingService(_CapturedService):
        def project(self, request):
            type(self).calls += 1
            raise ValueError("sensitive SQL experiment contradiction")

    monkeypatch.setattr(
        route_module,
        "EconomicRecommendationExperimentDesignService",
        RejectingService,
    )

    payload = _payload()
    payload["experiment_design_inputs"][0]["approved_dimensions"][0]["value"] = 99

    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=payload,
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "sensitive" not in detail
    assert "SQL" not in detail
    assert "frozen optimization contract" in detail


def test_response_serializes_exact_19_field_m11a10_row_and_complete_a8_row(api_auth_headers):
    _CapturedService.rows = (_design_row(),)

    response = _client(api_auth_headers).post(
        "/optimization/experiment-designs/project",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["experiment_designs"]
    assert len(body["experiment_designs"]) == 1

    row = body["experiment_designs"][0]
    assert list(row.keys()) == [
        "experiment_reference",
        "approved_recommendation_row",
        "hypothesis",
        "control_definition",
        "treatment_definition",
        "success_measure",
        "observation_window",
        "actor_reference",
        "decision_reference",
        "decided_at",
        "design_reference",
        "designed_at",
        "recommendation_policy_version",
        "approval_policy_version",
        "experiment_design_policy_version",
        "source_approval_semantics",
        "source_approval_contract_version",
        "experiment_design_semantics",
        "experiment_design_contract_version",
    ]

    approved = row["approved_recommendation_row"]
    assert list(approved.keys()) == [
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
    assert approved["dimensions"] == [
        {"name": "affiliate_program", "value": 7}
    ]
    assert approved["operating_profit"] == "123.45"
    assert isinstance(approved["operating_profit"], str)

    assert row["actor_reference"] == "human-reviewer-001"
    assert row["decision_reference"] == "decision-001"
    assert row["decided_at"] == "2026-09-04T01:00:00+00:00"
    assert row["designed_at"] == "2026-09-04T02:00:00+00:00"
    assert row["source_approval_semantics"] == ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS
    assert row["source_approval_contract_version"] == (
        ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
    )
    assert row["experiment_design_semantics"] == (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
    )
    assert row["experiment_design_contract_version"] == (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
    )

    forbidden = {
        "budget",
        "allocation",
        "traffic",
        "schedule",
        "launch",
        "execution",
        "action",
        "dispatch",
        "platform",
        "publish",
    }
    assert forbidden.isdisjoint(row.keys())
    assert forbidden.isdisjoint(approved.keys())
