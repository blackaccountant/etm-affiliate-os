from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.optimization.eligible_economic_candidate_contracts import (
    ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION,
    ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS,
    EligibleEconomicCandidateRow,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
)
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OperatingProfitEvidenceEligibilityPolicy,
)
from app.services.eligible_economic_candidate_service import (
    EligibleEconomicCandidateService,
    _CapturingOperatingProfitSignalService,
)


POLICY = OperatingProfitEvidenceEligibilityPolicy("policy", 1, 1, 1)
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request():
    return EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), "USD", POLICY, WHEN).normalized()


def _candidate(value=1):
    return SimpleNamespace(
        currency="USD", dimensions=(("affiliate_program", value),), evaluated_at=WHEN,
        policy_version="policy", policy_fingerprint=POLICY.fingerprint(),
        source_evidence_semantics="evidence", source_evidence_contract_version="e1",
        source_eligibility_semantics="eligibility", source_eligibility_contract_version="i1",
        candidate_set_semantics="candidate", candidate_set_contract_version="c1",
    )


def _signal(value=1, profit=Decimal("1.00"), currency="USD", dimensions=None):
    return SimpleNamespace(
        currency=currency, dimensions=dimensions or (("affiliate_program", value),),
        operating_profit=profit, source_semantics="operating", signal_semantics="signal",
        signal_contract_version="s1",
    )


def test_contract_and_exact_row_manifest_are_frozen_and_economic_only():
    assert ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION == "m11a5b-eligible-economic-candidate-v1"
    assert "ranking" in ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS and "action" in ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
    assert tuple(EligibleEconomicCandidateRow.__dataclass_fields__) == (
        "currency", "dimensions", "operating_profit", "evaluated_at", "policy_version", "policy_fingerprint",
        "source_operating_profit_semantics", "source_signal_semantics", "source_signal_contract_version",
        "source_evidence_semantics", "source_evidence_contract_version", "source_eligibility_semantics",
        "source_eligibility_contract_version", "source_candidate_set_semantics",
        "source_candidate_set_contract_version", "eligible_economic_candidate_semantics",
        "eligible_economic_candidate_contract_version",
    )
    assert "ROI" not in EligibleEconomicCandidateRow.__dataclass_fields__


def test_frozen_request_is_reused_without_a_new_request_contract():
    assert EligibleEconomicCandidateService.project.__annotations__["request"] is EligibleOperatingProfitCandidateSetRequest


def test_association_preserves_exact_decimal_object_and_candidate_order():
    first, second = _signal(1, Decimal("-2.00")), _signal(2, Decimal("100.00"))
    rows = EligibleEconomicCandidateService._associate((_candidate(2), _candidate(1)), (first, second), _request())
    assert [row.dimensions for row in rows] == [_candidate(2).dimensions, _candidate(1).dimensions]
    assert rows[1].operating_profit is first.operating_profit
    assert rows[0].operating_profit == Decimal("100.00")


def test_missing_or_duplicate_signal_identity_fails_closed():
    with pytest.raises(ValueError, match="no captured"):
        EligibleEconomicCandidateService._associate((_candidate(),), (), _request())
    with pytest.raises(ValueError, match="duplicate"):
        EligibleEconomicCandidateService._associate((_candidate(),), (_signal(), _signal()), _request())


def test_extra_signals_are_legal_and_empty_candidates_remain_empty():
    assert EligibleEconomicCandidateService._associate((), (_signal(2),), _request()) == ()
    rows = EligibleEconomicCandidateService._associate((_candidate(1),), (_signal(1), _signal(2)), _request())
    assert len(rows) == 1 and rows[0].dimensions == _candidate(1).dimensions


@pytest.mark.parametrize("candidate, signal", [
    (_candidate(), _signal(currency="EUR")),
    (_candidate(), _signal(dimensions=(("product", 1),))),
    (SimpleNamespace(**{**_candidate().__dict__, "policy_version": "other"}), _signal()),
])
def test_request_or_signal_contradictions_fail_closed(candidate, signal):
    with pytest.raises(ValueError):
        EligibleEconomicCandidateService._associate((candidate,), (signal,), _request())


def test_capture_returns_exact_tuple_and_never_leaks_stale_rows():
    rows = (_signal(),)
    class Delegate:
        def project(self, request): return rows
    capture = _CapturingOperatingProfitSignalService(Delegate())
    capture.begin_capture()
    assert capture.project(object()) is rows and capture.finish_capture() is rows
    with pytest.raises(RuntimeError): capture.project(object())
    capture.begin_capture()
    with pytest.raises(ValueError): capture.finish_capture()


def test_capture_rejects_second_m11a1_traversal():
    class Delegate:
        def project(self, request): return ()
    capture = _CapturingOperatingProfitSignalService(Delegate())
    capture.begin_capture()
    capture.project(object())
    with pytest.raises(ValueError, match="exactly one"):
        capture.project(object())
