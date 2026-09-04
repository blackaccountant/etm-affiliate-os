"""HTTP transport over frozen M11A10 approved experiment-design projection."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.optimization_approval_routes import (
    _domain_request as _approval_domain_request,
    _serialize_datetime,
    _serialize_recommendation_row,
)
from app.api.optimization_experiment_design_schemas import (
    UIF4AExperimentDesignProjectionRequest,
    UIF4AExperimentDesignProjectionResponse,
    UIF4AExperimentDesignResponseRow,
)
from app.dependencies import get_db
from app.optimization.economic_recommendation_experiment_design_contracts import (
    EconomicRecommendationExperimentDesignInput,
    EconomicRecommendationExperimentDesignPolicy,
    EconomicRecommendationExperimentDesignRequest,
    EconomicRecommendationExperimentDesignRow,
)
from app.services.economic_recommendation_experiment_design_service import (
    EconomicRecommendationExperimentDesignService,
)


router = APIRouter(
    prefix="/optimization/experiment-designs",
    tags=["Optimization Experiment Designs"],
)


def _domain_request(
    request: UIF4AExperimentDesignProjectionRequest,
) -> EconomicRecommendationExperimentDesignRequest:
    design_inputs = tuple(
        EconomicRecommendationExperimentDesignInput(
            experiment_reference=item.experiment_reference,
            approved_dimensions=tuple(
                (dimension.name, dimension.value)
                for dimension in item.approved_dimensions
            ),
            hypothesis=item.hypothesis,
            control_definition=item.control_definition,
            treatment_definition=item.treatment_definition,
            success_measure=item.success_measure,
            observation_window=item.observation_window,
            design_reference=item.design_reference,
            designed_at=item.designed_at,
        )
        for item in request.experiment_design_inputs
    )

    return EconomicRecommendationExperimentDesignRequest(
        approval_request=_approval_domain_request(request.approval_request),
        experiment_design_inputs=design_inputs,
        experiment_design_policy=EconomicRecommendationExperimentDesignPolicy(
            policy_version=request.experiment_design_policy.policy_version
        ),
    )


def _serialize_design_row(
    row: EconomicRecommendationExperimentDesignRow,
) -> UIF4AExperimentDesignResponseRow:
    return UIF4AExperimentDesignResponseRow(
        experiment_reference=row.experiment_reference,
        approved_recommendation_row=_serialize_recommendation_row(
            row.approved_recommendation_row
        ),
        hypothesis=row.hypothesis,
        control_definition=row.control_definition,
        treatment_definition=row.treatment_definition,
        success_measure=row.success_measure,
        observation_window=row.observation_window,
        actor_reference=row.actor_reference,
        decision_reference=row.decision_reference,
        decided_at=_serialize_datetime(row.decided_at),
        design_reference=row.design_reference,
        designed_at=_serialize_datetime(row.designed_at),
        recommendation_policy_version=row.recommendation_policy_version,
        approval_policy_version=row.approval_policy_version,
        experiment_design_policy_version=row.experiment_design_policy_version,
        source_approval_semantics=row.source_approval_semantics,
        source_approval_contract_version=row.source_approval_contract_version,
        experiment_design_semantics=row.experiment_design_semantics,
        experiment_design_contract_version=row.experiment_design_contract_version,
    )


@router.post(
    "/project",
    response_model=UIF4AExperimentDesignProjectionResponse,
    status_code=status.HTTP_200_OK,
)
def project_experiment_designs(
    request: UIF4AExperimentDesignProjectionRequest,
    db: Session = Depends(get_db),
):
    try:
        domain_request = _domain_request(request)
        # Validate the complete frozen request before traversing the service graph.
        domain_request.normalized()
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="experiment design projection request violates frozen contract",
        ) from exc

    service = EconomicRecommendationExperimentDesignService(db)

    try:
        rows = service.project(domain_request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="experiment design projection rejected by frozen optimization contract",
        ) from exc

    if type(rows) is not tuple or any(
        type(row) is not EconomicRecommendationExperimentDesignRow
        for row in rows
    ):
        raise RuntimeError("frozen M11A10 experiment design service returned invalid type")

    return UIF4AExperimentDesignProjectionResponse(
        experiment_designs=[
            _serialize_design_row(row)
            for row in rows
        ]
    )
