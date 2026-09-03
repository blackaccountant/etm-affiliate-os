from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
from app.optimization.eligible_economic_candidate_contracts import EligibleEconomicCandidateRow
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import (
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION,
    ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS,
    OrderedEconomicCandidatePreferenceRequest,
    OrderedEconomicCandidatePreferenceRow,
)
from app.services.ordered_economic_candidate_preference_service import (
    OrderedEconomicCandidatePreferenceService,
    _CapturedEligibleEconomicCandidateService,
)


WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = OperatingProfitEvidenceEligibilityPolicy("eligible", 1, 1, 1)
COMPARISON = OperatingProfitComparisonPolicy("pairwise-v1")


def _candidate_request():
    return EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), "USD", POLICY, WHEN).normalized()


def _request(policy=COMPARISON):
    return OrderedEconomicCandidatePreferenceRequest(_candidate_request(), policy)


def _candidate(identity, profit=Decimal("1.00"), **overrides):
    values = dict(
        currency="USD", dimensions=(("affiliate_program", identity),), operating_profit=profit,
        evaluated_at=WHEN, policy_version="eligible", policy_fingerprint=POLICY.fingerprint(),
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
    source = _Candidates(tuple(rows))
    return OrderedEconomicCandidatePreferenceService(None, economic_candidate_service=source), source


def _tiers(rows): return [(dict(row.dimensions)["affiliate_program"], row.preference_tier) for row in rows]


def test_contract_manifests_semantics_and_immutability_are_exact():
    assert ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION == "m11a7-ordered-economic-candidate-preference-v1"
    for term in ("read-only", "deterministic", "complete", "M11A5B", "M11A6", "dense-tier", "presentation only", "no FX", "no score", "no recommendation", "no selection", "no allocation", "no action"):
        assert term in ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS
    assert tuple(OrderedEconomicCandidatePreferenceRequest.__dataclass_fields__) == ("candidate_request", "comparison_policy")
    assert tuple(OrderedEconomicCandidatePreferenceRow.__dataclass_fields__) == (
        "currency", "dimensions", "operating_profit", "preference_tier", "evaluated_at",
        "eligibility_policy_version", "eligibility_policy_fingerprint", "comparison_policy_version",
        "source_economic_candidate_semantics", "source_economic_candidate_contract_version",
        "source_pairwise_comparison_semantics", "source_pairwise_comparison_contract_version",
        "ordered_preference_semantics", "ordered_preference_contract_version",
    )
    assert len(fields(OrderedEconomicCandidatePreferenceRow)) == 14
    with pytest.raises(FrozenInstanceError): _request().comparison_policy = COMPARISON


@pytest.mark.parametrize("preference_request", [
    OrderedEconomicCandidatePreferenceRequest(None, COMPARISON),
    OrderedEconomicCandidatePreferenceRequest(_candidate_request(), OperatingProfitComparisonPolicy("")),
    OrderedEconomicCandidatePreferenceRequest(_candidate_request(), object()),
])
def test_request_reuses_frozen_authorities_and_rejects_invalid_values(preference_request):
    with pytest.raises(ValueError): preference_request.normalized()
    normalized = _request().normalized()
    assert normalized.candidate_request == _candidate_request() and normalized.comparison_policy is COMPARISON


def test_empty_and_singleton_are_valid_one_source_projection_cases():
    service, source = _service()
    assert service.project(_request()) == () and source.calls == 1
    candidate = _candidate(1, Decimal("9")); service, source = _service(candidate)
    row = service.project(_request())[0]
    assert source.calls == 1 and row.preference_tier == 1 and row.operating_profit is candidate.operating_profit


@pytest.mark.parametrize("overrides", [
    {"currency": "EUR"}, {"dimensions": (("product", 1),)},
    {"evaluated_at": datetime(2026, 1, 2, tzinfo=timezone.utc)}, {"policy_version": "other"},
    {"policy_fingerprint": "other"}, {"eligible_economic_candidate_semantics": "other"},
    {"eligible_economic_candidate_contract_version": "other"}, {"operating_profit": 1},
    {"dimensions": (("affiliate_program", True),)},
])
def test_local_envelope_validation_applies_to_every_candidate_including_singletons(overrides):
    service, _ = _service(_candidate(1, **overrides))
    with pytest.raises(ValueError, match="contradicts"): service.project(_request())


def test_duplicate_identity_fails_closed_before_ordering():
    service, _ = _service(_candidate(1), _candidate(1))
    with pytest.raises(ValueError, match="duplicate"): service.project(_request())


def test_ordering_dense_tiers_canonical_ties_and_exact_decimal_propagation():
    candidates = (_candidate(3, Decimal("80")), _candidate(1, Decimal("100")), _candidate(4, Decimal("50")), _candidate(2, Decimal("80")))
    service, _ = _service(*candidates)
    rows = service.project(_request())
    assert _tiers(rows) == [(1, 1), (2, 2), (3, 2), (4, 3)]
    assert rows[0].operating_profit is candidates[1].operating_profit
    assert rows[1].operating_profit is candidates[3].operating_profit


def test_negative_zero_and_reverse_canonical_identity_do_not_override_m11a6_economics():
    service, _ = _service(_candidate(1, Decimal("-5")), _candidate(2, Decimal("0")), _candidate(3, Decimal("-1")))
    assert _tiers(service.project(_request())) == [(2, 1), (3, 2), (1, 3)]


def test_cached_pairs_are_composed_once_and_less_than_all_pairs_for_eight_candidates():
    service, source = _service(*[_candidate(index, Decimal(str(9 - index))) for index in range(8)])
    calls, real = [], service._pairwise.project
    def tracked(request): calls.append((request.left_dimensions, request.right_dimensions)); return real(request)
    service._pairwise.project = tracked
    rows = service.project(_request())
    assert source.calls == 1 and len(calls) == len(set(calls)) and len(calls) < 28
    assert [row.preference_tier for row in rows] == list(range(1, 9))


def test_adapter_returns_exact_tuple_validates_request_and_clears_state():
    adapter, rows = _CapturedEligibleEconomicCandidateService(), (_candidate(1),)
    with pytest.raises(RuntimeError, match="absent"): adapter.project(_candidate_request())
    adapter.load(_candidate_request(), rows)
    assert adapter.project(_candidate_request()) is rows
    wrong = EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), "EUR", POLICY, WHEN)
    with pytest.raises(ValueError, match="contradicts"): adapter.project(wrong)
    adapter.clear()
    with pytest.raises(RuntimeError, match="absent"): adapter.project(_candidate_request())


def test_adapter_clears_after_success_and_pairwise_result_failures():
    service, _ = _service(_candidate(1), _candidate(2))
    service.project(_request()); assert service._captured_candidates._request is None
    class Invalid:
        def project(self, request): return object()
    service._pairwise = Invalid()
    with pytest.raises(ValueError, match="pairwise result"): service.project(_request())
    assert service._captured_candidates._request is None


def test_constructor_preserves_falsey_source_and_production_has_no_lower_authority_or_raw_profit_ordering():
    source = _Candidates(())
    assert OrderedEconomicCandidatePreferenceService(None, economic_candidate_service=source)._economic_candidates is source
    text = Path(__file__).parents[1].joinpath("app/services/ordered_economic_candidate_preference_service.py").read_text(encoding="utf-8")
    forbidden = ("OperatingProfitSignalService", "OperatingProfitEvidenceService", "EligibleOperatingProfitCandidateSetService", ".execute(", ".commit(", ".rollback(", ".flush(", "requests", "httpx", "operating_profit >", "operating_profit <", "profit_difference", "recommendation", "winner")
    assert not [term for term in forbidden if term in text]
