import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_contracts import OperatingProfitEvidenceRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy, OperatingProfitEvidenceEligibilityRequest
from app.services.eligible_operating_profit_candidate_set_service import EligibleOperatingProfitCandidateSetService
from app.services.operating_profit_evidence_eligibility_service import OperatingProfitEvidenceEligibilityService
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


def test_optional_collaborators_are_keyword_only_and_defaults_are_unchanged():
    for cls, name, expected in ((OperatingProfitEvidenceService, "signal_service", OperatingProfitSignalService), (OperatingProfitEvidenceEligibilityService, "evidence_service", OperatingProfitEvidenceService), (EligibleOperatingProfitCandidateSetService, "eligibility_service", OperatingProfitEvidenceEligibilityService)):
        parameter = inspect.signature(cls).parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
        assert isinstance(cls(SimpleNamespace()).__dict__[{'signal_service':'_signals','evidence_service':'_evidence','eligibility_service':'_eligibility'}[name]], expected)


@pytest.mark.parametrize("cls, keyword, attribute", [
    (OperatingProfitEvidenceService, "signal_service", "_signals"),
    (OperatingProfitEvidenceEligibilityService, "evidence_service", "_evidence"),
    (EligibleOperatingProfitCandidateSetService, "eligibility_service", "_eligibility"),
])
def test_injected_and_falsey_collaborators_are_retained(cls, keyword, attribute):
    class Falsey:
        def __bool__(self): return False
    supplied = Falsey()
    assert getattr(cls(SimpleNamespace(), **{keyword: supplied}), attribute) is supplied


def test_injected_chain_forwards_once_and_never_calls_in_constructors():
    calls = []
    evidence_row = SimpleNamespace(currency="USD", dimensions=(("affiliate_program", 1),), settled_earning_count=1, settled_conversion_count=1, settlement_link_count=1, attribution_click_count=0, first_settlement_observed_at=datetime(2026,1,1,tzinfo=timezone.utc), latest_settlement_observed_at=datetime(2026,1,1,tzinfo=timezone.utc), evidence_semantics="e", evidence_contract_version="e1")
    class Signal:
        def project(self, request): calls.append("signal"); return ()
    class Evidence:
        def project(self, request): calls.append("evidence"); return (evidence_row,)
    class Eligibility:
        def project(self, request):
            calls.append("eligibility")
            return (SimpleNamespace(currency="USD", dimensions=(("affiliate_program",1),), eligible=True, reason_codes=(), evaluated_at=request.evaluated_at, policy_version=request.policy.policy_version, policy_fingerprint=request.policy.fingerprint(), source_evidence_semantics="e", source_evidence_contract_version="e1", assessment_semantics="a", assessment_contract_version="a1"),)
    signal, evidence, eligibility = Signal(), Evidence(), Eligibility()
    assert OperatingProfitEvidenceService(None, signal_service=signal)._signals is signal
    assert OperatingProfitEvidenceEligibilityService(None, evidence_service=evidence)._evidence is evidence
    candidate = EligibleOperatingProfitCandidateSetService(None, eligibility_service=eligibility)
    request = EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), "USD", OperatingProfitEvidenceEligibilityPolicy("p",1,1,1), datetime(2026,1,1,tzinfo=timezone.utc))
    assert candidate.project(request) and calls == ["eligibility"]


def test_unusable_collaborator_fails_closed_at_project_use():
    service = OperatingProfitEvidenceEligibilityService(None, evidence_service=object())
    with pytest.raises(AttributeError):
        service.project(OperatingProfitEvidenceEligibilityRequest(policy=OperatingProfitEvidenceEligibilityPolicy("p",1,1,1), evaluated_at=datetime(2026,1,1,tzinfo=timezone.utc)))
