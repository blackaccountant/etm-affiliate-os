"""Read and command API for durable discovery runs."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.dependencies import get_discovery_mission_manager, get_discovery_query_service, get_discovery_run_orchestration_service, get_discovery_run_repository
from app.discovery.contracts import DiscoveryRunCreate, DiscoveryRunStatus
from app.mission.manager import MissionManager
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.schemas.discovery import DiscoveryCandidateResponse, DiscoveryExecuteRequest, DiscoveryExecutionResponse, DiscoveryMissionLaunchRequest, DiscoveryMissionLaunchResponse, DiscoveryRankingItemResponse, DiscoveryRankingResponse, DiscoveryRunCreateRequest, DiscoveryRunResponse, DiscoverySelectedResponse, EvidenceObservationResponse
from app.services.discovery_mission_launch_service import DiscoveryMissionLaunchService
from app.services.discovery_query_service import DiscoveryQueryService
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService


router = APIRouter()


def _run_or_404(service: DiscoveryQueryService, run_id: str):
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="discovery run not found")
    return run


@router.post("/runs", response_model=DiscoveryRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(payload: DiscoveryRunCreateRequest, repository: DiscoveryRunRepository = Depends(get_discovery_run_repository)):
    try:
        return repository.create(DiscoveryRunCreate.model_validate(payload.model_dump()))
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error


@router.post("/runs/{run_id}/execute", response_model=DiscoveryExecutionResponse)
def execute_run(run_id: str, payload: DiscoveryExecuteRequest, service: DiscoveryRunOrchestrationService = Depends(get_discovery_run_orchestration_service)):
    try:
        result = service.execute(run_id, payload.top_n, payload.minimum_score, payload.minimum_evidence_confidence)
    except ValueError as error:
        message = str(error)
        code = 404 if "does not exist" in message else 400 if "unsupported" in message else 422
        raise HTTPException(status_code=code, detail=message) from error
    except RuntimeError as error:
        message = str(error)
        if "already running" in message or "requires explicit retry" in message:
            raise HTTPException(status_code=409, detail=message) from error
        raise
    return DiscoveryExecutionResponse(
        run=DiscoveryRunResponse.model_validate(result.run),
        ranked_candidate_ids=list(result.ranked_candidate_ids),
        selected_candidate_ids=list(result.selected_candidate_ids),
    )


@router.get("/runs/{run_id}", response_model=DiscoveryRunResponse)
def get_run(run_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    return _run_or_404(service, run_id)


@router.get("/runs/{run_id}/candidates", response_model=list[DiscoveryCandidateResponse])
def list_candidates(run_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    _run_or_404(service, run_id)
    return service.list_candidates(run_id)


@router.get("/runs/{run_id}/ranking", response_model=DiscoveryRankingResponse)
def get_ranking(run_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    _run_or_404(service, run_id)
    return DiscoveryRankingResponse(items=[DiscoveryRankingItemResponse(rank=index, candidate=DiscoveryCandidateResponse.model_validate(item.candidate), evidence_count=item.evidence_count) for index, item in enumerate(service.ranking(run_id), start=1)])


@router.get("/runs/{run_id}/selected", response_model=DiscoverySelectedResponse)
def get_selected(run_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    _run_or_404(service, run_id)
    return DiscoverySelectedResponse(candidates=[DiscoveryCandidateResponse.model_validate(item) for item in service.selected(run_id)])


@router.post("/runs/{run_id}/launch", response_model=DiscoveryMissionLaunchResponse)
def launch_run(run_id: str, payload: DiscoveryMissionLaunchRequest, mission_manager: MissionManager = Depends(get_discovery_mission_manager)):
    service = DiscoveryMissionLaunchService(mission_manager=mission_manager)
    try:
        result = service.launch(run_id, payload.top_n, payload.minimum_score, payload.minimum_evidence_confidence)
    except ValueError as error:
        message = str(error)
        code = 404 if "does not exist" in message else 400 if "input_type" in message or "unsupported" in message else 422
        raise HTTPException(status_code=code, detail=message) from error
    except RuntimeError as error:
        message = str(error)
        if "already" in message or "requires explicit retry" in message:
            raise HTTPException(status_code=409, detail=message) from error
        raise

    return DiscoveryMissionLaunchResponse(
        run_id=result.discovery_run_id,
        mission_id=result.mission_id,
        mission_status=result.mission_status,
        workflow=result.workflow,
        required_capability=result.required_capability,
        idempotency_key=result.idempotency_key,
        worker_name=result.worker_name,
        result_success=result.result_success,
        result_error=result.result_error,
        result_data=result.result_data,
    )


@router.get("/candidates/{candidate_id}", response_model=DiscoveryCandidateResponse)
def get_candidate(candidate_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    candidate = service.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="discovery candidate not found")
    return candidate


@router.get("/candidates/{candidate_id}/evidence", response_model=list[EvidenceObservationResponse])
def get_evidence(candidate_id: str, service: DiscoveryQueryService = Depends(get_discovery_query_service)):
    if service.get_candidate(candidate_id) is None:
        raise HTTPException(status_code=404, detail="discovery candidate not found")
    return service.list_evidence(candidate_id)
