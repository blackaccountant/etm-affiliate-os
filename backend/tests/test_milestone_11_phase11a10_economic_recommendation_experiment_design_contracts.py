from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
from app.optimization.economic_recommendation_approval_contracts import (
    ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
    EconomicRecommendationApprovalDecision,
    EconomicRecommendationApprovalOutcome,
    EconomicRecommendationApprovalPolicy,
    EconomicRecommendationApprovalRequest,
    EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS,
    EconomicRecommendationExperimentDesignInput,
    EconomicRecommendationExperimentDesignPolicy,
    EconomicRecommendationExperimentDesignRequest,
    EconomicRecommendationExperimentDesignRow,
)
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
    EconomicRecommendationPolicy,
    EconomicRecommendationProposalRequest,
    EconomicRecommendationProposalRow,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest
from app.services.economic_recommendation_experiment_design_service import EconomicRecommendationExperimentDesignService

WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
DESIGNED = WHEN + timedelta(hours=1)


def _approval_request(state=EconomicRecommendationApprovalState.APPROVED, selected=((('affiliate_program', 1),),)):
    proposal = EconomicRecommendationProposalRequest(
        OrderedEconomicCandidatePreferenceRequest(
            EligibleOperatingProfitCandidateSetRequest(
                ('affiliate_program',), 'USD',
                OperatingProfitEvidenceEligibilityPolicy('eligibility-v1', 1, 1, 1), WHEN,
            ),
            OperatingProfitComparisonPolicy('comparison-v1'),
        ),
        EconomicRecommendationPolicy('recommendation-v1'),
    )
    return EconomicRecommendationApprovalRequest(
        proposal,
        EconomicRecommendationApprovalDecision(state, selected, 'actor-1', 'decision-1', WHEN),
        EconomicRecommendationApprovalPolicy('approval-v1'),
    )


def _proposal_row(value):
    request = _approval_request()
    candidate = request.proposal_request.preference_request.candidate_request
    return EconomicRecommendationProposalRow(
        'USD', (('affiliate_program', value),), Decimal('12.50'), 1, WHEN,
        'eligibility-v1', candidate.eligibility_policy.fingerprint(), 'comparison-v1',
        'recommendation-v1', 'source', 'source-v1',
        ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
        ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    )


def _outcome(state=EconomicRecommendationApprovalState.APPROVED, rows=None, selected=None):
    if rows is None:
        rows = (_proposal_row(1),) if state is EconomicRecommendationApprovalState.APPROVED else ()
    if selected is None:
        selected = tuple(row.dimensions for row in rows) if state is EconomicRecommendationApprovalState.APPROVED else ()
    request = _approval_request(state, selected)
    return request, EconomicRecommendationApprovalOutcome(
        'USD', state, tuple(rows), WHEN, 'actor-1', 'decision-1', WHEN,
        'recommendation-v1', 'approval-v1',
        ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
        ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
        ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
        ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    )


def _design(dimensions, ref='experiment-1', designed_at=DESIGNED):
    return EconomicRecommendationExperimentDesignInput(
        ref, dimensions, 'Treatment improves the declared success measure.',
        'Existing strategy', 'Approved recommendation treatment',
        'Operating-profit evidence', timedelta(days=14), f'design-{ref}', designed_at,
    )


def _request(approval_request, *designs):
    return EconomicRecommendationExperimentDesignRequest(
        approval_request, tuple(designs), EconomicRecommendationExperimentDesignPolicy('experiment-design-v1')
    )


class _ApprovalSource:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0
    def project(self, _request):
        self.calls += 1
        return self.outcome


def _project(approval_request, outcome, *designs):
    source = _ApprovalSource(outcome)
    result = EconomicRecommendationExperimentDesignService(
        None, recommendation_approval_service=source
    ).project(_request(approval_request, *designs))
    return source, result


def test_exact_dataclass_manifests_and_contract_version():
    assert ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION == 'm11a10-approved-economic-experiment-design-v1'
    assert [f.name for f in fields(EconomicRecommendationExperimentDesignPolicy)] == ['policy_version']
    assert [f.name for f in fields(EconomicRecommendationExperimentDesignInput)] == [
        'experiment_reference','approved_dimensions','hypothesis','control_definition',
        'treatment_definition','success_measure','observation_window','design_reference','designed_at'
    ]
    assert [f.name for f in fields(EconomicRecommendationExperimentDesignRequest)] == [
        'approval_request','experiment_design_inputs','experiment_design_policy'
    ]
    assert [f.name for f in fields(EconomicRecommendationExperimentDesignRow)] == [
        'experiment_reference','approved_recommendation_row','hypothesis','control_definition',
        'treatment_definition','success_measure','observation_window','actor_reference',
        'decision_reference','decided_at','design_reference','designed_at',
        'recommendation_policy_version','approval_policy_version','experiment_design_policy_version',
        'source_approval_semantics','source_approval_contract_version',
        'experiment_design_semantics','experiment_design_contract_version'
    ]


def test_contracts_are_frozen():
    policy = EconomicRecommendationExperimentDesignPolicy('v1')
    with pytest.raises(FrozenInstanceError):
        policy.policy_version = 'changed'
    design = _design((('affiliate_program', 1),))
    with pytest.raises(FrozenInstanceError):
        design.hypothesis = 'changed'


def test_policy_and_input_validation_fail_closed():
    with pytest.raises(ValueError):
        EconomicRecommendationExperimentDesignPolicy(' ').normalized()
    with pytest.raises(ValueError):
        _design((('affiliate_program', 1),), ref=' ').normalized()
    base = _design((('affiliate_program', 1),))
    for window in (timedelta(0), -timedelta(seconds=1)):
        with pytest.raises(ValueError):
            EconomicRecommendationExperimentDesignInput(
                base.experiment_reference, base.approved_dimensions, base.hypothesis,
                base.control_definition, base.treatment_definition, base.success_measure,
                window, base.design_reference, base.designed_at,
            ).normalized()
    with pytest.raises(ValueError):
        EconomicRecommendationExperimentDesignInput(
            base.experiment_reference, base.approved_dimensions, base.hypothesis,
            base.control_definition, base.treatment_definition, base.success_measure,
            base.observation_window, base.design_reference, datetime(2026,1,1),
        ).normalized()


def test_approved_zero_and_one_design_preserve_source_object_and_provenance():
    approval_request, outcome = _outcome()
    source, empty = _project(approval_request, outcome)
    assert source.calls == 1 and empty == ()
    source, result = _project(approval_request, outcome, _design(outcome.approved_rows[0].dimensions))
    assert source.calls == 1 and len(result) == 1
    row = result[0]
    assert row.approved_recommendation_row is outcome.approved_rows[0]
    assert row.approved_recommendation_row.operating_profit is outcome.approved_rows[0].operating_profit
    assert type(row.approved_recommendation_row.operating_profit) is Decimal
    assert (row.actor_reference, row.decision_reference, row.decided_at) == ('actor-1','decision-1',WHEN)
    assert row.recommendation_policy_version == 'recommendation-v1'
    assert row.approval_policy_version == 'approval-v1'
    assert row.source_approval_semantics == ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS
    assert row.source_approval_contract_version == ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
    assert row.experiment_design_semantics == ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS


def test_multiple_designs_normalize_output_to_m11a9_order():
    rows = (_proposal_row(1), _proposal_row(2))
    approval_request, outcome = _outcome(rows=rows)
    _, result = _project(
        approval_request, outcome,
        _design(rows[1].dimensions, 'experiment-2'),
        _design(rows[0].dimensions, 'experiment-1'),
    )
    assert [x.experiment_reference for x in result] == ['experiment-1','experiment-2']
    assert result[0].approved_recommendation_row is rows[0]
    assert result[1].approved_recommendation_row is rows[1]


def test_duplicate_experiment_reference_and_identity_fail():
    rows = (_proposal_row(1), _proposal_row(2))
    approval_request, outcome = _outcome(rows=rows)
    with pytest.raises(ValueError, match='duplicate experiment_reference'):
        _project(approval_request, outcome, _design(rows[0].dimensions,'same'), _design(rows[1].dimensions,'same'))
    with pytest.raises(ValueError, match='duplicate experiment design approved identity'):
        _project(approval_request, outcome, _design(rows[0].dimensions,'one'), _design(rows[0].dimensions,'two'))


def test_foreign_identity_fails_closed():
    approval_request, outcome = _outcome()
    with pytest.raises(ValueError, match='not approved'):
        _project(approval_request, outcome, _design((('affiliate_program',99),)))


@pytest.mark.parametrize('state',[EconomicRecommendationApprovalState.REJECTED,EconomicRecommendationApprovalState.DEFERRED])
def test_rejected_and_deferred_require_empty_designs(state):
    approval_request, outcome = _outcome(state)
    source, result = _project(approval_request, outcome)
    assert source.calls == 1 and result == ()
    with pytest.raises(ValueError, match='non-approved decision'):
        _project(approval_request, outcome, _design((('affiliate_program',1),)))


def test_designed_at_must_not_predate_approval():
    approval_request, outcome = _outcome()
    with pytest.raises(ValueError, match='predates approval'):
        _project(approval_request, outcome, _design(outcome.approved_rows[0].dimensions, designed_at=WHEN-timedelta(seconds=1)))


def test_source_outcome_provenance_mismatch_fails():
    approval_request, outcome = _outcome()
    bad = EconomicRecommendationApprovalOutcome(
        outcome.currency,outcome.decision_state,outcome.approved_rows,outcome.evaluated_at,
        'wrong-actor',outcome.decision_reference,outcome.decided_at,
        outcome.recommendation_policy_version,outcome.approval_policy_version,
        outcome.source_recommendation_semantics,outcome.source_recommendation_contract_version,
    )
    with pytest.raises(ValueError, match='contradicts'):
        _project(approval_request, bad)


def test_source_duplicate_or_reordered_rows_fail():
    row1, row2 = _proposal_row(1), _proposal_row(2)
    approval_request, duplicate = _outcome(rows=(row1,row1), selected=(row1.dimensions,row1.dimensions))
    with pytest.raises(ValueError):
        _project(approval_request, duplicate)
    approval_request, reordered = _outcome(rows=(row2,row1), selected=(row2.dimensions,row1.dimensions))
    with pytest.raises(ValueError, match='order'):
        _project(approval_request, reordered)


def test_request_requires_exact_tuple_and_exact_nested_contracts():
    approval_request, _ = _outcome()
    with pytest.raises(ValueError):
        EconomicRecommendationExperimentDesignRequest(
            approval_request, [], EconomicRecommendationExperimentDesignPolicy('v1')
        ).normalized()
    with pytest.raises(ValueError):
        EconomicRecommendationExperimentDesignRequest(
            approval_request, ('not-a-design',), EconomicRecommendationExperimentDesignPolicy('v1')
        ).normalized()
