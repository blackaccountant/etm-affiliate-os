"""Thin HTTP surface for durable, Mission-backed content work."""

import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import (
    get_content_generation_run_repository,
    get_content_mission_manager,
    get_content_repurposing_run_repository,
    get_db,
    get_generated_content_artifact_repository,
)
from app.mission.manager import MissionManager
from app.repositories.content_brief_repository import ContentBriefRepository
from app.repositories.content_evaluation_repository import ContentEvaluationRepository
from app.repositories.content_generation_run_repository import ContentGenerationRunRepository
from app.repositories.content_repurposing_run_repository import ContentRepurposingRunRepository
from app.repositories.generated_content_artifact_repository import GeneratedContentArtifactRepository
from app.repositories.mission_repository import MissionRepository
from app.schemas.content import (
    ContentBriefResponse,
    ContentEvaluationResponse,
    ContentGenerationRunResponse,
    ContentMissionLaunchResponse,
    ContentMissionResponse,
    ContentOperationsSnapshotResponse,
    ContentRepurposingRunResponse,
    GeneratedContentArtifactResponse,
)
from app.services.content_generation_mission_launch_service import ContentGenerationMissionLaunchService
from app.services.content_repurposing_mission_launch_service import ContentRepurposingMissionLaunchService


router = APIRouter(prefix="/content", tags=["Content"])


def _json_safe(value: Any) -> Any:
    """Keep the public result envelope to explicit JSON primitives only."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return {"value_type": type(value).__name__}


def _result_data(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"value_type": "invalid_json"}
    if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
        raw = raw["data"]
    return _json_safe(raw) if isinstance(raw, dict) else {"value_type": type(raw).__name__}


def _result_success(status: str) -> bool | None:
    return True if status == "COMPLETED" else False if status == "FAILED" else None


def _launch_response(result) -> ContentMissionLaunchResponse:
    return ContentMissionLaunchResponse(
        content_generation_run_id=getattr(result, "content_generation_run_id", None),
        content_repurposing_run_id=getattr(result, "content_repurposing_run_id", None),
        mission_id=result.mission_id,
        mission_status=result.mission_status,
        workflow=result.workflow,
        required_capability=result.required_capability,
        idempotency_key=result.idempotency_key,
        worker_name=result.worker_name,
        result_success=result.result_success,
        result_error=result.result_error,
        result_data=_result_data(result.result_data),
    )


def _launch_error(error: Exception) -> HTTPException | None:
    message = str(error)
    if isinstance(error, ValueError) and "does not exist" in message:
        return HTTPException(status_code=404, detail="content run not found")
    if isinstance(error, RuntimeError) and "already" in message:
        return HTTPException(status_code=409, detail="content run is not available for a fresh launch")
    return None


# UIF5C — read-only operator content visibility.
@router.get("/operations", response_model=ContentOperationsSnapshotResponse)
def get_content_operations(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return recent durable content records without launching or mutating work."""
    return ContentOperationsSnapshotResponse(
        briefs=[ContentBriefResponse.model_validate(item) for item in ContentBriefRepository(db).list_recent(limit)],
        generation_runs=[ContentGenerationRunResponse.model_validate(item) for item in ContentGenerationRunRepository(db).list_recent(limit)],
        artifacts=[GeneratedContentArtifactResponse.model_validate(item) for item in GeneratedContentArtifactRepository(db).list_recent(limit)],
        evaluations=[ContentEvaluationResponse.model_validate(item) for item in ContentEvaluationRepository(db).list_recent(limit)],
        repurposing_runs=[ContentRepurposingRunResponse.model_validate(item) for item in ContentRepurposingRunRepository(db).list_recent(limit)],
    )


@router.post("/generation-runs/{content_generation_run_id}/launch", response_model=ContentMissionLaunchResponse)
def launch_generation_run(
    content_generation_run_id: str,
    mission_manager: MissionManager = Depends(get_content_mission_manager),
):
    try:
        return _launch_response(ContentGenerationMissionLaunchService(mission_manager=mission_manager).launch(content_generation_run_id))
    except (ValueError, RuntimeError) as error:
        mapped = _launch_error(error)
        if mapped is not None:
            raise mapped from error
        raise


@router.post("/repurposing-runs/{content_repurposing_run_id}/launch", response_model=ContentMissionLaunchResponse)
def launch_repurposing_run(
    content_repurposing_run_id: str,
    mission_manager: MissionManager = Depends(get_content_mission_manager),
):
    try:
        return _launch_response(ContentRepurposingMissionLaunchService(mission_manager=mission_manager).launch(content_repurposing_run_id))
    except (ValueError, RuntimeError) as error:
        mapped = _launch_error(error)
        if mapped is not None:
            raise mapped from error
        raise


@router.get("/missions/{mission_id}", response_model=ContentMissionResponse)
def get_mission(mission_id: str, db: Session = Depends(get_db)):
    mission = MissionRepository(db).get_by_id(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="content mission not found")
    return ContentMissionResponse(
        id=mission.id,
        name=mission.name,
        objective=mission.objective,
        workflow=mission.workflow_name,
        required_capability=mission.required_capability,
        idempotency_key=mission.idempotency_key,
        status=mission.status,
        worker_name=mission.current_worker_name,
        result_success=_result_success(mission.status),
        result_error=mission.last_error,
        result_data=_result_data(mission.result_data),
        created_at=mission.created_at,
        updated_at=mission.updated_at,
    )


@router.get("/generation-runs/{run_id}", response_model=ContentGenerationRunResponse)
def get_generation_run(run_id: str, repository: ContentGenerationRunRepository = Depends(get_content_generation_run_repository)):
    run = repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="content generation run not found")
    return run


@router.get("/repurposing-runs/{run_id}", response_model=ContentRepurposingRunResponse)
def get_repurposing_run(run_id: str, repository: ContentRepurposingRunRepository = Depends(get_content_repurposing_run_repository)):
    run = repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="content repurposing run not found")
    return run


@router.get("/artifacts/{artifact_id}", response_model=GeneratedContentArtifactResponse)
def get_artifact(artifact_id: str, repository: GeneratedContentArtifactRepository = Depends(get_generated_content_artifact_repository)):
    artifact = repository.get_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="generated content artifact not found")
    return artifact
