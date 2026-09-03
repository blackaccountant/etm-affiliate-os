from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone

import pytest

from app.optimization.operating_profit_evidence_contracts import (
    OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION,
    OPERATING_PROFIT_EVIDENCE_SEMANTICS,
)
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_CONTRACT_VERSION,
    OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_SEMANTICS,
    REASONS,
    OperatingProfitEvidenceEligibilityPolicy,
    OperatingProfitEvidenceEligibilityRequest,
    OperatingProfitEvidenceEligibilityRow,
)
from app.services.operating_profit_evidence_eligibility_service import (
    OperatingProfitEvidenceEligibilityService,
)


def policy(**kwargs):
    return OperatingProfitEvidenceEligibilityPolicy("v1", 1, 1, 1, **kwargs)


def test_contract_manifests_constants_and_policy_fingerprint():
    assert [field.name for field in fields(OperatingProfitEvidenceEligibilityPolicy)] == [
        "policy_version", "minimum_settled_earning_count",
        "minimum_settled_conversion_count", "minimum_settlement_link_count",
        "minimum_attribution_click_count", "maximum_settlement_observation_age",
    ]
    assert [field.name for field in fields(OperatingProfitEvidenceEligibilityRequest)] == [
        "dimensions", "currency", "policy", "evaluated_at",
    ]
    assert [field.name for field in fields(OperatingProfitEvidenceEligibilityRow)] == [
        "currency", "dimensions", "eligible", "reason_codes", "evaluated_at",
        "source_evidence_semantics", "source_evidence_contract_version",
        "policy_version", "policy_fingerprint", "assessment_semantics",
        "assessment_contract_version",
    ]
    assert OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_CONTRACT_VERSION == "m11a3-evidence-eligibility-v1"
    assert "financial quality" in OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_SEMANTICS
    assert len(policy().fingerprint()) == 64
    assert policy().fingerprint() == policy().fingerprint()
    assert policy(maximum_settlement_observation_age=timedelta(microseconds=1)).fingerprint() != policy().fingerprint()


@pytest.mark.parametrize("bad", [
    OperatingProfitEvidenceEligibilityPolicy("", 0, 0, 0),
    OperatingProfitEvidenceEligibilityPolicy("v", True, 0, 0),
    OperatingProfitEvidenceEligibilityPolicy("v", -1, 0, 0),
    OperatingProfitEvidenceEligibilityPolicy("v", 0, 0, 0, minimum_attribution_click_count="0"),
    OperatingProfitEvidenceEligibilityPolicy("v", 0, 0, 0, maximum_settlement_observation_age=timedelta(microseconds=-1)),
])
def test_policy_rejects_invalid_thresholds_and_age(bad):
    with pytest.raises(ValueError):
        bad.normalized()


@pytest.mark.parametrize("evaluated_at", [None, datetime.now(), datetime.now(timezone(timedelta(hours=1)))])
def test_request_requires_policy_and_exact_utc_evaluation(evaluated_at):
    with pytest.raises(ValueError):
        OperatingProfitEvidenceEligibilityRequest(policy=policy(), evaluated_at=evaluated_at).normalized()
    with pytest.raises(ValueError):
        OperatingProfitEvidenceEligibilityRequest(evaluated_at=datetime.now(timezone.utc)).normalized()
    assert OperatingProfitEvidenceEligibilityRequest(policy=policy(), evaluated_at=datetime.now(timezone.utc)).normalized().policy == policy()


def test_service_orders_reasons_and_excludes_evaluation_from_fingerprint(monkeypatch):
    observed = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @dataclass(frozen=True)
    class Evidence:
        currency: str = "USD"
        dimensions: tuple = (("affiliate_program", "program"),)
        settled_earning_count: int = 0
        settled_conversion_count: int = 0
        settlement_link_count: int = 0
        attribution_click_count: int = 0
        first_settlement_observed_at: datetime = observed
        latest_settlement_observed_at: datetime = observed
        evidence_semantics: str = OPERATING_PROFIT_EVIDENCE_SEMANTICS
        evidence_contract_version: str = OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION

    service = OperatingProfitEvidenceEligibilityService(None)
    monkeypatch.setattr(service._evidence, "project", lambda request: (Evidence(),))
    p = policy(minimum_attribution_click_count=1, maximum_settlement_observation_age=timedelta())
    first = service.project(OperatingProfitEvidenceEligibilityRequest(policy=p, evaluated_at=observed))[0]
    second = service.project(OperatingProfitEvidenceEligibilityRequest(policy=p, evaluated_at=observed + timedelta(seconds=1)))[0]
    assert first.eligible is False and first.reason_codes == REASONS[:4]
    assert second.reason_codes == REASONS and first.policy_fingerprint == second.policy_fingerprint
    assert first.assessment_semantics == OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_SEMANTICS


@pytest.mark.parametrize("first, latest, evaluated_at", [
    (datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
    (datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)),
    (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
])
def test_service_fails_closed_for_malformed_source_evidence(monkeypatch, first, latest, evaluated_at):
    evidence = type("Evidence", (), {
        "currency": "USD", "dimensions": (), "settled_earning_count": 1,
        "settled_conversion_count": 1, "settlement_link_count": 1,
        "attribution_click_count": 0, "first_settlement_observed_at": first,
        "latest_settlement_observed_at": latest,
        "evidence_semantics": OPERATING_PROFIT_EVIDENCE_SEMANTICS,
        "evidence_contract_version": OPERATING_PROFIT_EVIDENCE_CONTRACT_VERSION,
    })()
    service = OperatingProfitEvidenceEligibilityService(None)
    monkeypatch.setattr(service._evidence, "project", lambda request: (evidence,))
    with pytest.raises(ValueError):
        service.project(OperatingProfitEvidenceEligibilityRequest(policy=policy(), evaluated_at=evaluated_at))
