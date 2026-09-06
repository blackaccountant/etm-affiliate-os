"""Focused contracts for M11A11 economic experiment activation authorization."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.optimization.economic_recommendation_experiment_activation_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS,
    EconomicRecommendationExperimentActivationDecision,
    EconomicRecommendationExperimentActivationPolicy,
    EconomicRecommendationExperimentActivationRequest,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS,
    EconomicRecommendationExperimentDesignRow,
)
from app.services.economic_recommendation_experiment_activation_service import (
    EconomicRecommendationExperimentActivationService,
)


NOW = datetime(
    2026,
    9,
    6,
    5,
    0,
    tzinfo=timezone.utc,
)


def design_row(
    *,
    experiment_reference="experiment-1",
    design_reference="design-1",
    designed_at=NOW,
    decided_at=None,
):
    return EconomicRecommendationExperimentDesignRow(
        experiment_reference=experiment_reference,
        approved_recommendation_row=object(),
        hypothesis="treatment improves operating profit",
        control_definition="retain current allocation",
        treatment_definition="apply approved treatment",
        success_measure="operating profit",
        observation_window=timedelta(days=7),
        actor_reference="approval-actor",
        decision_reference="approval-decision",
        decided_at=(
            NOW - timedelta(minutes=10)
            if decided_at is None
            else decided_at
        ),
        design_reference=design_reference,
        designed_at=designed_at,
        recommendation_policy_version="recommendation-v1",
        approval_policy_version="approval-v1",
        experiment_design_policy_version="design-v1",
        source_approval_semantics="approval-semantics",
        source_approval_contract_version="approval-contract-v1",
        experiment_design_semantics=(
            ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
        ),
        experiment_design_contract_version=(
            ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
        ),
    )


class StubDesignService:
    def __init__(self, rows):
        self.rows = rows

    def project(self, request):
        return self.rows


def decision(
    *,
    experiment_reference="experiment-1",
    activation_reference="activation-1",
    actor_reference="activation-actor",
    decision_reference="activation-decision-1",
    authorized_at=NOW + timedelta(minutes=1),
):
    return EconomicRecommendationExperimentActivationDecision(
        experiment_reference=experiment_reference,
        activation_reference=activation_reference,
        actor_reference=actor_reference,
        decision_reference=decision_reference,
        authorized_at=authorized_at,
    )


def normalized_request(*decisions):
    class Request:
        experiment_design_request = object()
        activation_decisions = tuple(
            item.normalized()
            for item in decisions
        )
        activation_policy = (
            EconomicRecommendationExperimentActivationPolicy(
                "activation-v1"
            ).normalized()
        )

    return Request()


def service_with(rows):
    return EconomicRecommendationExperimentActivationService(
        None,
        experiment_design_service=StubDesignService(
            rows
        ),
    )


def test_activation_contract_metadata_is_frozen():
    assert (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION
        == "m11a11-economic-experiment-activation-authorization-v1"
    )

    semantics = (
        ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS
    )

    assert "authorization" in semantics
    assert "no operation specification" in semantics
    assert "no Mission creation" in semantics
    assert "no Worker claim" in semantics
    assert "no Execution creation" in semantics
    assert "no lease acquisition" in semantics
    assert "no scheduling" in semantics
    assert "no dispatch" in semantics
    assert "no platform action" in semantics
    assert "no traffic mutation" in semantics
    assert "no attribution mutation" in semantics
    assert "no economic inference" in semantics


def test_activation_policy_normalizes_version():
    policy = (
        EconomicRecommendationExperimentActivationPolicy(
            " activation-v1 "
        ).normalized()
    )

    assert policy.policy_version == "activation-v1"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        None,
        1,
    ],
)
def test_activation_policy_rejects_invalid_version(
    value,
):
    with pytest.raises(
        ValueError,
        match="policy version must be nonblank",
    ):
        EconomicRecommendationExperimentActivationPolicy(
            value
        ).normalized()


def test_activation_decision_normalizes_text():
    normalized = (
        EconomicRecommendationExperimentActivationDecision(
            experiment_reference=" experiment-1 ",
            activation_reference=" activation-1 ",
            actor_reference=" actor-1 ",
            decision_reference=" decision-1 ",
            authorized_at=NOW,
        ).normalized()
    )

    assert (
        normalized.experiment_reference
        == "experiment-1"
    )

    assert (
        normalized.activation_reference
        == "activation-1"
    )

    assert normalized.actor_reference == "actor-1"
    assert normalized.decision_reference == "decision-1"
    assert normalized.authorized_at == NOW


@pytest.mark.parametrize(
    (
        "field",
        "value",
    ),
    [
        ("experiment_reference", ""),
        ("experiment_reference", "   "),
        ("activation_reference", ""),
        ("actor_reference", None),
        ("decision_reference", 1),
    ],
)
def test_activation_decision_rejects_invalid_text(
    field,
    value,
):
    values = {
        "experiment_reference": "experiment-1",
        "activation_reference": "activation-1",
        "actor_reference": "actor-1",
        "decision_reference": "decision-1",
        "authorized_at": NOW,
    }

    values[field] = value

    with pytest.raises(
        ValueError,
        match="text fields must be nonblank",
    ):
        EconomicRecommendationExperimentActivationDecision(
            **values
        ).normalized()


def test_activation_decision_requires_utc_authorization_time():
    with pytest.raises(
        ValueError,
        match="timezone-aware UTC",
    ):
        decision(
            authorized_at=datetime(
                2026,
                9,
                6,
                5,
                1,
            ),
        ).normalized()

    with pytest.raises(
        ValueError,
        match="timezone-aware UTC",
    ):
        decision(
            authorized_at=datetime(
                2026,
                9,
                6,
                6,
                1,
                tzinfo=timezone(
                    timedelta(hours=1)
                ),
            ),
        ).normalized()


def test_activation_request_requires_exact_design_request_type():
    with pytest.raises(
        ValueError,
        match="experiment design request is required",
    ):
        EconomicRecommendationExperimentActivationRequest(
            experiment_design_request=object(),
            activation_decisions=(),
            activation_policy=(
                EconomicRecommendationExperimentActivationPolicy(
                    "activation-v1"
                )
            ),
        ).normalized()


def test_activation_request_requires_tuple_decisions():
    fake_design_request = object.__new__(
        __import__(
            "app.optimization."
            "economic_recommendation_experiment_design_contracts",
            fromlist=[
                "EconomicRecommendationExperimentDesignRequest"
            ],
        ).EconomicRecommendationExperimentDesignRequest
    )

    with pytest.raises(
        ValueError,
        match="activation_decisions must be a tuple",
    ):
        EconomicRecommendationExperimentActivationRequest(
            experiment_design_request=fake_design_request,
            activation_decisions=[],
            activation_policy=(
                EconomicRecommendationExperimentActivationPolicy(
                    "activation-v1"
                )
            ),
        ).normalized()


def test_activation_request_requires_exact_policy_type():
    fake_design_request = object.__new__(
        __import__(
            "app.optimization."
            "economic_recommendation_experiment_design_contracts",
            fromlist=[
                "EconomicRecommendationExperimentDesignRequest"
            ],
        ).EconomicRecommendationExperimentDesignRequest
    )

    with pytest.raises(
        ValueError,
        match="activation policy is required",
    ):
        EconomicRecommendationExperimentActivationRequest(
            experiment_design_request=fake_design_request,
            activation_decisions=(),
            activation_policy=object(),
        ).normalized()


def test_activation_request_rejects_non_decision_items():
    fake_design_request = object.__new__(
        __import__(
            "app.optimization."
            "economic_recommendation_experiment_design_contracts",
            fromlist=[
                "EconomicRecommendationExperimentDesignRequest"
            ],
        ).EconomicRecommendationExperimentDesignRequest
    )

    with pytest.raises(
        ValueError,
        match="invalid activation decision",
    ):
        EconomicRecommendationExperimentActivationRequest(
            experiment_design_request=fake_design_request,
            activation_decisions=(object(),),
            activation_policy=(
                EconomicRecommendationExperimentActivationPolicy(
                    "activation-v1"
                )
            ),
        ).normalized()


def test_service_projects_deterministic_activation_authorization():
    source = design_row()

    rows = service_with(
        (source,)
    )._bind_decisions(
        (source,),
        normalized_request(
            decision()
        ),
    )

    assert len(rows) == 1

    row = rows[0]

    assert row.experiment_reference == "experiment-1"
    assert row.activation_reference == "activation-1"
    assert row.actor_reference == "activation-actor"
    assert (
        row.decision_reference
        == "activation-decision-1"
    )

    assert row.hypothesis == source.hypothesis
    assert (
        row.control_definition
        == source.control_definition
    )
    assert (
        row.treatment_definition
        == source.treatment_definition
    )
    assert (
        row.success_measure
        == source.success_measure
    )
    assert (
        row.observation_window
        == source.observation_window
    )

    assert row.design_reference == "design-1"
    assert row.designed_at == NOW

    assert (
        row.recommendation_policy_version
        == "recommendation-v1"
    )
    assert (
        row.approval_policy_version
        == "approval-v1"
    )
    assert (
        row.experiment_design_policy_version
        == "design-v1"
    )
    assert (
        row.activation_policy_version
        == "activation-v1"
    )

    assert (
        row.source_experiment_design_semantics
        == ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_SEMANTICS
    )

    assert (
        row.source_experiment_design_contract_version
        == ECONOMIC_RECOMMENDATION_EXPERIMENT_DESIGN_CONTRACT_VERSION
    )

    assert (
        row.activation_semantics
        == ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_SEMANTICS
    )

    assert (
        row.activation_contract_version
        == ECONOMIC_RECOMMENDATION_EXPERIMENT_ACTIVATION_CONTRACT_VERSION
    )


def test_activation_row_exposes_no_operation_authority():
    source = design_row()

    row = service_with(
        (source,)
    )._bind_decisions(
        (source,),
        normalized_request(
            decision()
        ),
    )[0]

    for forbidden in (
        "workflow",
        "required_capability",
        "idempotency_key",
        "payload",
    ):
        assert not hasattr(
            row,
            forbidden,
        )


def test_projection_is_deterministic():
    source = design_row()
    request = normalized_request(
        decision()
    )

    service = service_with(
        (source,)
    )

    first = service._bind_decisions(
        (source,),
        request,
    )

    second = service._bind_decisions(
        (source,),
        request,
    )

    assert first == second


def test_projection_preserves_m11a10_design_order():
    first = design_row(
        experiment_reference="experiment-1",
        design_reference="design-1",
    )

    second = design_row(
        experiment_reference="experiment-2",
        design_reference="design-2",
    )

    request = normalized_request(
        decision(
            experiment_reference="experiment-2",
            activation_reference="activation-2",
            decision_reference="decision-2",
        ),
        decision(
            experiment_reference="experiment-1",
            activation_reference="activation-1",
            decision_reference="decision-1",
        ),
    )

    rows = service_with(
        (first, second)
    )._bind_decisions(
        (first, second),
        request,
    )

    assert tuple(
        row.experiment_reference
        for row in rows
    ) == (
        "experiment-1",
        "experiment-2",
    )


def test_activation_can_authorize_subset_of_designs():
    first = design_row(
        experiment_reference="experiment-1",
    )

    second = design_row(
        experiment_reference="experiment-2",
        design_reference="design-2",
    )

    rows = service_with(
        (first, second)
    )._bind_decisions(
        (first, second),
        normalized_request(
            decision(
                experiment_reference="experiment-2",
                activation_reference="activation-2",
            )
        ),
    )

    assert len(rows) == 1
    assert (
        rows[0].experiment_reference
        == "experiment-2"
    )


def test_unknown_experiment_reference_is_rejected():
    source = design_row()

    with pytest.raises(
        ValueError,
        match="experiment_reference is not present",
    ):
        service_with(
            (source,)
        )._bind_decisions(
            (source,),
            normalized_request(
                decision(
                    experiment_reference=(
                        "unknown-experiment"
                    ),
                )
            ),
        )


def test_duplicate_activation_for_same_experiment_is_rejected():
    source = design_row()

    with pytest.raises(
        ValueError,
        match="duplicate activation decision for experiment",
    ):
        service_with(
            (source,)
        )._bind_decisions(
            (source,),
            normalized_request(
                decision(),
                decision(
                    activation_reference="activation-2",
                    decision_reference="decision-2",
                ),
            ),
        )


def test_duplicate_activation_reference_is_rejected():
    first = design_row(
        experiment_reference="experiment-1",
    )

    second = design_row(
        experiment_reference="experiment-2",
        design_reference="design-2",
    )

    with pytest.raises(
        ValueError,
        match="duplicate activation_reference",
    ):
        service_with(
            (first, second)
        )._bind_decisions(
            (first, second),
            normalized_request(
                decision(
                    experiment_reference="experiment-1",
                    activation_reference="same-activation",
                    decision_reference="decision-1",
                ),
                decision(
                    experiment_reference="experiment-2",
                    activation_reference="same-activation",
                    decision_reference="decision-2",
                ),
            ),
        )


def test_duplicate_activation_decision_reference_is_rejected():
    first = design_row(
        experiment_reference="experiment-1",
    )

    second = design_row(
        experiment_reference="experiment-2",
        design_reference="design-2",
    )

    with pytest.raises(
        ValueError,
        match="duplicate activation decision_reference",
    ):
        service_with(
            (first, second)
        )._bind_decisions(
            (first, second),
            normalized_request(
                decision(
                    experiment_reference="experiment-1",
                    activation_reference="activation-1",
                    decision_reference="same-decision",
                ),
                decision(
                    experiment_reference="experiment-2",
                    activation_reference="activation-2",
                    decision_reference="same-decision",
                ),
            ),
        )


def test_activation_cannot_predate_design():
    source = design_row(
        designed_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="predates experiment design",
    ):
        service_with(
            (source,)
        )._bind_decisions(
            (source,),
            normalized_request(
                decision(
                    authorized_at=(
                        NOW
                        - timedelta(seconds=1)
                    ),
                )
            ),
        )


def test_activation_cannot_predate_approval():
    source = design_row(
        designed_at=NOW - timedelta(minutes=20),
        decided_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="predates recommendation approval",
    ):
        service_with(
            (source,)
        )._bind_decisions(
            (source,),
            normalized_request(
                decision(
                    authorized_at=(
                        NOW
                        - timedelta(minutes=1)
                    ),
                )
            ),
        )


def test_invalid_m11a10_row_type_is_rejected():
    with pytest.raises(
        ValueError,
        match="row type is invalid",
    ):
        service_with(
            (object(),)
        )._bind_decisions(
            (object(),),
            normalized_request(),
        )


def test_invalid_m11a10_contract_lineage_is_rejected():
    source = design_row()

    tampered = EconomicRecommendationExperimentDesignRow(
        **{
            **source.__dict__,
            "experiment_design_contract_version": (
                "tampered-version"
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="experiment design lineage is invalid",
    ):
        service_with(
            (tampered,)
        )._bind_decisions(
            (tampered,),
            normalized_request(
                decision()
            ),
        )


def test_duplicate_m11a10_experiment_reference_is_rejected():
    first = design_row()

    duplicate = design_row(
        design_reference="design-2",
    )

    with pytest.raises(
        ValueError,
        match="duplicate M11A10 experiment_reference",
    ):
        service_with(
            (first, duplicate)
        )._bind_decisions(
            (first, duplicate),
            normalized_request(
                decision()
            ),
        )


def test_non_tuple_m11a10_outcome_is_rejected():
    with pytest.raises(
        ValueError,
        match="outcome must be a tuple",
    ):
        service_with(
            []
        )._bind_decisions(
            [],
            normalized_request(),
        )


def test_empty_design_set_rejects_activation_decisions():
    with pytest.raises(
        ValueError,
        match="activation decisions require M11A10 experiment designs",
    ):
        service_with(
            ()
        )._bind_decisions(
            (),
            normalized_request(
                decision()
            ),
        )


def test_empty_design_set_and_no_activation_is_empty_projection():
    assert (
        service_with(
            ()
        )._bind_decisions(
            (),
            normalized_request(),
        )
        == ()
    )


def test_activation_contract_dataclasses_are_frozen():
    policy = (
        EconomicRecommendationExperimentActivationPolicy(
            "activation-v1"
        )
    )

    with pytest.raises(
        FrozenInstanceError
    ):
        policy.policy_version = "changed"

    activation = decision()

    with pytest.raises(
        FrozenInstanceError
    ):
        activation.activation_reference = "changed"
