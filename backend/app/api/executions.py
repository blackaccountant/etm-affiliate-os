"""
Execution API

Provides mission and workflow execution history.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.services.execution_service import (
    ExecutionService,
)

from app.dependencies import (
    get_execution_service,
)

from app.schemas.execution import (
    ExecutionResponse,
)


router = APIRouter(
    prefix="/executions",
    tags=["Executions"],
)


@router.get(
    "/",
    response_model=list[ExecutionResponse],
)
def list_executions(
    limit: int = 10,
    service: ExecutionService = Depends(
        get_execution_service
    ),
):

    return service.get_recent(
        limit
    )


@router.get(
    "/{execution_id}",
    response_model=ExecutionResponse,
)
def get_execution(
    execution_id: int,
    service: ExecutionService = Depends(
        get_execution_service
    ),
):

    execution = service.get_by_id(
        execution_id
    )

    if not execution:

        raise HTTPException(
            status_code=404,
            detail="Execution not found",
        )

    return execution


@router.get(
    "/mission/{mission_id}",
    response_model=list[ExecutionResponse],
)
def get_mission_executions(
    mission_id: str,
    service: ExecutionService = Depends(
        get_execution_service
    ),
):

    return service.get_by_mission_id(
        mission_id
    )