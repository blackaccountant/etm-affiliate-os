"""Bind externally supplied experiment designs to frozen M11A9 approvals."""

from decimal import Decimal

from app.optimization.economic_recommendation_approval_contracts import (
    ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS,
    EconomicRecommendationApprovalOutcome,
    EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    EconomicRecommendationExperimentDesignRequest,
    EconomicRecommendationExperimentDesignRow,
)
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
    EconomicRecommendationProposalRow,
)
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    canonical_bucket_identity,
)
from app.services.economic_recommendation_approval_service import (
    EconomicRecommendationApprovalService,
)


class EconomicRecommendationExperimentDesignService:
    def __init__(self, db, *, recommendation_approval_service=None):
        self._approvals = (
            EconomicRecommendationApprovalService(db)
            if recommendation_approval_service is None
            else recommendation_approval_service
        )

    @staticmethod
    def _validate_dimensions(dimensions, requested_names):
        if type(dimensions) is not tuple or len(dimensions) != len(requested_names):
            raise ValueError("experiment design dimensions contradict the requested grain")
        for pair, name in zip(dimensions, requested_names, strict=True):
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or pair[0] != name
                or (type(pair[1]) not in (str, int) and pair[1] is not None)
            ):
                raise ValueError("experiment design dimensions contradict the requested grain")

    @classmethod
    def _validate_source(cls, outcome, normalized):
        if type(outcome) is not EconomicRecommendationApprovalOutcome:
            raise ValueError("M11A9 approval outcome type is invalid")

        approval_request = normalized.approval_request
        proposal_request = approval_request.proposal_request
        preference_request = proposal_request.preference_request
        candidate_request = preference_request.candidate_request
        decision = approval_request.approval_decision
        requested_names = candidate_request.dimensions
        expected_fingerprint = candidate_request.eligibility_policy.fingerprint()

        if (
            type(outcome.decision_state) is not EconomicRecommendationApprovalState
            or outcome.decision_state is not decision.decision_state
            or type(outcome.approved_rows) is not tuple
            or outcome.currency != candidate_request.currency
            or outcome.evaluated_at != candidate_request.evaluated_at
            or outcome.actor_reference != decision.actor_reference
            or outcome.decision_reference != decision.decision_reference
            or outcome.decided_at != decision.decided_at
            or outcome.recommendation_policy_version != proposal_request.recommendation_policy.policy_version
            or outcome.approval_policy_version != approval_request.approval_policy.policy_version
            or outcome.source_recommendation_semantics != ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
            or outcome.source_recommendation_contract_version != ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
            or outcome.approval_semantics != ECONOMIC_RECOMMENDATION_APPROVAL_SEMANTICS
            or outcome.approval_contract_version != ECONOMIC_RECOMMENDATION_APPROVAL_CONTRACT_VERSION
        ):
            raise ValueError("M11A9 outcome contradicts the M11A10 request")

        if decision.decided_at < candidate_request.evaluated_at:
            raise ValueError("approval decision predates evaluation")

        expected_approved_identities = []
        for dimensions in decision.approved_dimensions:
            cls._validate_dimensions(dimensions, requested_names)
            expected_approved_identities.append(
                canonical_bucket_identity(candidate_request.currency, dimensions)
            )

        identities = []
        previous_identity = None
        for row in outcome.approved_rows:
            if (
                type(row) is not EconomicRecommendationProposalRow
                or row.currency != candidate_request.currency
                or type(row.operating_profit) is not Decimal
                or type(row.preference_tier) is not int
                or type(row.preference_tier) is bool
                or row.preference_tier != 1
                or row.evaluated_at != candidate_request.evaluated_at
                or row.eligibility_policy_version != candidate_request.eligibility_policy.policy_version
                or row.eligibility_policy_fingerprint != expected_fingerprint
                or row.comparison_policy_version != preference_request.comparison_policy.policy_version
                or row.recommendation_policy_version != proposal_request.recommendation_policy.policy_version
                or row.recommendation_proposal_semantics != ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
                or row.recommendation_proposal_contract_version != ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
            ):
                raise ValueError("M11A9 approved row contradicts the M11A10 request")

            cls._validate_dimensions(row.dimensions, requested_names)
            identity = canonical_bucket_identity(row.currency, row.dimensions)
            if identity in identities:
                raise ValueError("duplicate M11A9 approved identity")
            if previous_identity is not None and previous_identity >= identity:
                raise ValueError("M11A9 approved-row order is invalid")
            identities.append(identity)
            previous_identity = identity

        if outcome.decision_state is EconomicRecommendationApprovalState.APPROVED:
            if not identities or identities != expected_approved_identities:
                raise ValueError("M11A9 approved rows contradict the approval decision")
        elif expected_approved_identities or identities:
            raise ValueError("non-approved M11A9 outcome cannot carry approved rows")

        return identities

    @classmethod
    def _bind_inputs(cls, outcome, identities, normalized):
        inputs = normalized.experiment_design_inputs
        if outcome.decision_state is not EconomicRecommendationApprovalState.APPROVED:
            if inputs:
                raise ValueError("non-approved decision cannot carry experiment designs")
            return ()

        candidate_request = normalized.approval_request.proposal_request.preference_request.candidate_request
        requested_names = candidate_request.dimensions
        index_by_identity = {identity: index for index, identity in enumerate(identities)}
        by_identity = {}
        seen_experiment_references = set()

        for item in inputs:
            cls._validate_dimensions(item.approved_dimensions, requested_names)
            identity = canonical_bucket_identity(candidate_request.currency, item.approved_dimensions)
            if identity not in index_by_identity:
                raise ValueError("experiment design identity is not approved by M11A9")
            if identity in by_identity:
                raise ValueError("duplicate experiment design approved identity")
            if item.experiment_reference in seen_experiment_references:
                raise ValueError("duplicate experiment_reference")
            if item.designed_at < outcome.decided_at:
                raise ValueError("experiment design predates approval decision")
            by_identity[identity] = item
            seen_experiment_references.add(item.experiment_reference)

        rows = []
        for identity, approved_row in zip(identities, outcome.approved_rows, strict=True):
            item = by_identity.get(identity)
            if item is None:
                continue
            rows.append(
                EconomicRecommendationExperimentDesignRow(
                    experiment_reference=item.experiment_reference,
                    approved_recommendation_row=approved_row,
                    hypothesis=item.hypothesis,
                    control_definition=item.control_definition,
                    treatment_definition=item.treatment_definition,
                    success_measure=item.success_measure,
                    observation_window=item.observation_window,
                    actor_reference=outcome.actor_reference,
                    decision_reference=outcome.decision_reference,
                    decided_at=outcome.decided_at,
                    design_reference=item.design_reference,
                    designed_at=item.designed_at,
                    recommendation_policy_version=outcome.recommendation_policy_version,
                    approval_policy_version=outcome.approval_policy_version,
                    experiment_design_policy_version=normalized.experiment_design_policy.policy_version,
                    source_approval_semantics=outcome.approval_semantics,
                    source_approval_contract_version=outcome.approval_contract_version,
                )
            )
        return tuple(rows)

    def project(self, request: EconomicRecommendationExperimentDesignRequest):
        normalized = request.normalized()
        outcome = self._approvals.project(normalized.approval_request)
        identities = self._validate_source(outcome, normalized)
        return self._bind_inputs(outcome, identities, normalized)
