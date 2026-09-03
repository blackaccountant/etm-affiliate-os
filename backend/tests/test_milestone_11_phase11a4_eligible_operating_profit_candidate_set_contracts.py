from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.optimization.eligible_operating_profit_candidate_set_contracts import *
from app.optimization.operating_profit_evidence_eligibility_contracts import *
from app.services.eligible_operating_profit_candidate_set_service import EligibleOperatingProfitCandidateSetService


def policy(): return OperatingProfitEvidenceEligibilityPolicy("p", 1, 1, 1)
def request(**kwargs): return EligibleOperatingProfitCandidateSetRequest(dimensions=("affiliate_program",), currency="USD", eligibility_policy=policy(), evaluated_at=datetime(2026, 1, 1, tzinfo=timezone.utc), **kwargs)
def assessment(**kwargs):
    values = dict(currency="USD", dimensions=(("affiliate_program", 1),), eligible=True, reason_codes=(), evaluated_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_evidence_semantics="e", source_evidence_contract_version="e1", policy_version="p", policy_fingerprint=policy().fingerprint(), assessment_semantics="a", assessment_contract_version="a1")
    values.update(kwargs); return SimpleNamespace(**values)


def test_manifests_and_currency_requirement():
    assert [field.name for field in fields(EligibleOperatingProfitCandidateSetRequest)] == ["dimensions", "currency", "eligibility_policy", "evaluated_at"]
    assert [field.name for field in fields(EligibleOperatingProfitCandidateRow)] == ["currency", "dimensions", "evaluated_at", "policy_version", "policy_fingerprint", "source_evidence_semantics", "source_evidence_contract_version", "source_eligibility_semantics", "source_eligibility_contract_version", "candidate_set_semantics", "candidate_set_contract_version"]
    assert "no money" in ELIGIBLE_OPERATING_PROFIT_CANDIDATE_SET_SEMANTICS
    with pytest.raises(ValueError): EligibleOperatingProfitCandidateSetRequest(eligibility_policy=policy(), evaluated_at=datetime(2026,1,1,tzinfo=timezone.utc)).normalized()


@pytest.mark.parametrize("value, expected", [(None, ("none", "")), (2, ("int", "2")), ("2", ("str", "2"))])
def test_canonical_identity_preserves_types(value, expected):
    assert canonical_bucket_identity("USD", (("x", value),))[1][0][1:] == expected


def test_service_filters_sorts_and_composes_once(monkeypatch):
    service, calls = EligibleOperatingProfitCandidateSetService(None), []
    rows = (assessment(dimensions=(("affiliate_program", "z"),)), assessment(dimensions=(("affiliate_program", 2),)), assessment(dimensions=(("affiliate_program", 1),), eligible=False, reason_codes=("INSUFFICIENT_SETTLED_EARNINGS",)))
    monkeypatch.setattr(service._eligibility, "project", lambda value: calls.append(value) or rows)
    result = service.project(request())
    assert len(calls) == 1 and [row.dimensions for row in result] == [(("affiliate_program", 2),), (("affiliate_program", "z"),)]
    assert all("profit" not in field and field not in {"rank", "score", "recommendation"} for field in EligibleOperatingProfitCandidateRow.__dataclass_fields__)


@pytest.mark.parametrize("bad", [
    dict(eligible=True, reason_codes=("x",)), dict(eligible=False, reason_codes=()),
    dict(currency="EUR"), dict(policy_version="other"), dict(policy_fingerprint="x"),
    dict(dimensions=(("product", 1),)), dict(evaluated_at=datetime(2026, 1, 2, tzinfo=timezone.utc)),
])
def test_service_fails_closed_for_contradictory_assessments(monkeypatch, bad):
    service = EligibleOperatingProfitCandidateSetService(None)
    monkeypatch.setattr(service._eligibility, "project", lambda value: (assessment(**bad),))
    with pytest.raises(ValueError): service.project(request())


def test_duplicate_and_empty_sets(monkeypatch):
    service = EligibleOperatingProfitCandidateSetService(None)
    monkeypatch.setattr(service._eligibility, "project", lambda value: (assessment(), assessment()))
    with pytest.raises(ValueError): service.project(request())
    monkeypatch.setattr(service._eligibility, "project", lambda value: (assessment(eligible=False, reason_codes=("x",)),))
    assert service.project(request()) == ()
