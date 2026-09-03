from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.optimization.economic_candidate_comparison_contracts import (
    ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION,
    ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS,
    EconomicCandidatePairwiseComparisonRequest,
    EconomicCandidatePairwiseComparisonRow,
    EconomicCandidatePairwiseRelation,
    OperatingProfitComparisonPolicy,
)
from app.optimization.eligible_economic_candidate_contracts import EligibleEconomicCandidateRow
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
)
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OperatingProfitEvidenceEligibilityPolicy,
)
from app.services.economic_candidate_comparison_service import EconomicCandidateComparisonService


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
ELIGIBILITY = OperatingProfitEvidenceEligibilityPolicy("eligible", 1, 1, 1)
COMPARISON = OperatingProfitComparisonPolicy("pairwise-v1")


def _candidate_request():
    return EligibleOperatingProfitCandidateSetRequest(
        ("affiliate_program",), "USD", ELIGIBILITY, WHEN,
    ).normalized()


def _request(left=1, right=2, policy=COMPARISON):
    return EconomicCandidatePairwiseComparisonRequest(
        _candidate_request(), (("affiliate_program", left),), (("affiliate_program", right),), policy,
    )


def _candidate(identity, profit=Decimal("1.00"), **overrides):
    values = dict(
        currency="USD", dimensions=(("affiliate_program", identity),), operating_profit=profit,
        evaluated_at=WHEN, policy_version="eligible", policy_fingerprint=ELIGIBILITY.fingerprint(),
        source_operating_profit_semantics="operating", source_signal_semantics="signal",
        source_signal_contract_version="signal-v1", source_evidence_semantics="evidence",
        source_evidence_contract_version="evidence-v1", source_eligibility_semantics="eligibility",
        source_eligibility_contract_version="eligibility-v1", source_candidate_set_semantics="set",
        source_candidate_set_contract_version="set-v1",
    )
    values.update(overrides)
    return EligibleEconomicCandidateRow(**values)


class _Candidates:
    def __init__(self, rows): self.rows, self.calls = rows, 0
    def project(self, request): self.calls += 1; return self.rows


def _service(*rows):
    collaborator = _Candidates(tuple(rows))
    return EconomicCandidateComparisonService(None, economic_candidate_service=collaborator), collaborator


def test_contract_semantics_policy_and_relation_are_exact_and_immutable():
    assert ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_CONTRACT_VERSION == "m11a6-economic-candidate-pairwise-comparison-v1"
    for term in ("read-only", "deterministic", "pairwise", "higher exact operating_profit", "no FX", "no ranking", "no recommendation", "no action"):
        assert term in ECONOMIC_CANDIDATE_PAIRWISE_COMPARISON_SEMANTICS
    assert tuple(OperatingProfitComparisonPolicy.__dataclass_fields__) == ("policy_version",)
    assert {member.name: member.value for member in EconomicCandidatePairwiseRelation} == {
        "LEFT_PREFERRED": "LEFT_PREFERRED", "TIE": "TIE", "RIGHT_PREFERRED": "RIGHT_PREFERRED",
    }
    with pytest.raises(FrozenInstanceError): COMPARISON.policy_version = "other"


def test_request_and_result_manifests_are_exact_immutable_and_economic_only():
    assert tuple(EconomicCandidatePairwiseComparisonRequest.__dataclass_fields__) == (
        "candidate_request", "left_dimensions", "right_dimensions", "comparison_policy",
    )
    assert tuple(EconomicCandidatePairwiseComparisonRow.__dataclass_fields__) == (
        "currency", "left_dimensions", "left_operating_profit", "right_dimensions", "right_operating_profit",
        "relation", "evaluated_at", "eligibility_policy_version", "eligibility_policy_fingerprint",
        "comparison_policy_version", "source_economic_candidate_semantics",
        "source_economic_candidate_contract_version", "pairwise_comparison_semantics",
        "pairwise_comparison_contract_version",
    )
    assert len(fields(EconomicCandidatePairwiseComparisonRow)) == 14
    assert not {"profit_difference", "rank", "score", "recommendation", "winner_id", "ROI", "margin"} & set(EconomicCandidatePairwiseComparisonRow.__dataclass_fields__)
    with pytest.raises(FrozenInstanceError): _request().left_dimensions = ()


@pytest.mark.parametrize("policy", [OperatingProfitComparisonPolicy(""), OperatingProfitComparisonPolicy(" "), OperatingProfitComparisonPolicy(1)])
def test_policy_rejects_blank_or_invalid_versions(policy):
    with pytest.raises(ValueError): _request(policy=policy).normalized()


@pytest.mark.parametrize("left,right", [
    ((("product", 1),), (("affiliate_program", 2),)),
    ((("affiliate_program", 1), ("product", 2)), (("affiliate_program", 2),)),
    ((("affiliate_program", True),), (("affiliate_program", 2),)),
    ((("affiliate_program", object()),), (("affiliate_program", 2),)),
])
def test_request_reuses_frozen_candidate_request_and_rejects_invalid_grain_or_values(left, right):
    request = EconomicCandidatePairwiseComparisonRequest(_candidate_request(), left, right, COMPARISON)
    with pytest.raises(ValueError): request.normalized()


def test_normalization_preserves_dimension_order_and_rejects_self_comparison():
    normalized = _request().normalized()
    assert normalized.candidate_request is not _candidate_request() and normalized.left_dimensions == (("affiliate_program", 1),)
    with pytest.raises(ValueError, match="self-comparison"):
        _request(1, 1).normalized()


def test_one_upstream_call_exact_decimal_propagation_and_left_preferred():
    left, right = _candidate(1, Decimal("2.00")), _candidate(2, Decimal("1.00"))
    service, collaborator = _service(left, right)
    result = service.project(_request())
    assert collaborator.calls == 1 and result.relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
    assert result.left_operating_profit is left.operating_profit and result.right_operating_profit is right.operating_profit
    assert result.comparison_policy_version == "pairwise-v1"


@pytest.mark.parametrize(("left", "right", "relation"), [
    (Decimal("1.00"), Decimal("2.00"), EconomicCandidatePairwiseRelation.RIGHT_PREFERRED),
    (Decimal("-5.00"), Decimal("-5.00"), EconomicCandidatePairwiseRelation.TIE),
    (Decimal("-10.00"), Decimal("-20.00"), EconomicCandidatePairwiseRelation.LEFT_PREFERRED),
    (Decimal("0.00"), Decimal("-1.00"), EconomicCandidatePairwiseRelation.LEFT_PREFERRED),
])
def test_exact_decimal_comparison_supports_right_tie_negative_and_zero(left, right, relation):
    service, _ = _service(_candidate(1, left), _candidate(2, right))
    assert service.project(_request()).relation is relation


def test_orientation_is_caller_owned_and_antisymmetric():
    service, collaborator = _service(_candidate(1, Decimal("9")), _candidate(2, Decimal("1")))
    assert service.project(_request(1, 2)).relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
    assert service.project(_request(2, 1)).relation is EconomicCandidatePairwiseRelation.RIGHT_PREFERRED
    assert collaborator.calls == 2


def test_missing_sides_duplicate_anywhere_extra_rows_and_context_contradictions_fail_closed():
    service, _ = _service(_candidate(1))
    with pytest.raises(ValueError, match="right"): service.project(_request())
    service, _ = _service(_candidate(2))
    with pytest.raises(ValueError, match="left"): service.project(_request())
    service, _ = _service(_candidate(1), _candidate(2), _candidate(3), _candidate(3))
    with pytest.raises(ValueError, match="duplicate"): service.project(_request())
    service, _ = _service(_candidate(1), _candidate(2), _candidate(3))
    assert service.project(_request()).relation is EconomicCandidatePairwiseRelation.TIE
    service, _ = _service(_candidate(1), _candidate(2, currency="EUR"))
    with pytest.raises(ValueError, match="contradicts"): service.project(_request())


def test_context_provenance_and_empty_tuple_fail_closed():
    bad = _candidate(2, eligible_economic_candidate_semantics="wrong")
    service, _ = _service(_candidate(1), bad)
    with pytest.raises(ValueError, match="contradicts"): service.project(_request())
    service, _ = _service()
    with pytest.raises(ValueError, match="left"): service.project(_request())


@pytest.mark.parametrize("overrides", [
    {"currency": "EUR"},
    {"dimensions": (("product", 2),)},
    {"evaluated_at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
    {"policy_version": "other"},
    {"policy_fingerprint": "other"},
    {"eligible_economic_candidate_semantics": "other"},
    {"eligible_economic_candidate_contract_version": "other"},
    {"operating_profit": 1},
    {"dimensions": (("affiliate_program", True),)},
])
def test_every_m11a5b_candidate_field_is_validated_before_pair_selection(overrides):
    service, _ = _service(_candidate(1), _candidate(2), _candidate(3, **overrides))
    with pytest.raises(ValueError, match="contradicts"):
        service.project(_request())


def test_duplicate_extra_identity_fails_before_selected_pair_is_returned():
    service, _ = _service(_candidate(1), _candidate(2), _candidate(3), _candidate(3))
    with pytest.raises(ValueError, match="duplicate"):
        service.project(_request())


def test_constructor_seam_preserves_falsey_collaborator_and_static_boundary_is_clean():
    collaborator = _Candidates(())
    assert EconomicCandidateComparisonService(None, economic_candidate_service=collaborator)._economic_candidates is collaborator
    source = Path(__file__).parents[1].joinpath("app/services/economic_candidate_comparison_service.py").read_text(encoding="utf-8")
    forbidden = ("OperatingProfitSignalService", "OperatingProfitEvidenceService", "OperatingProfitEvidenceEligibilityService", "EligibleOperatingProfitCandidateSetService", ".execute(", ".commit(", ".rollback(", ".flush(", "requests", "httpx")
    assert not [term for term in forbidden if term in source]
