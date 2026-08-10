"""
System Routes

Mission Control API endpoints
for ETM Affiliate OS.
"""

from fastapi import APIRouter

from app.system.intelligence import SystemIntelligence
from app.system.runtime import RuntimeAdapter
from app.system.dashboard import DashboardService

from app.scheduler.scheduler import Scheduler

from app.system.models import (
    SystemStatus,
    SystemSummary,
    WorkerStatus,
    QueueStatus,
    MemoryStatus,
    EventStatus,
    ExecutionStatus,
    RunWorkflowRequest,
    RunWorkflowResponse,
    CommandResponse,
    ProductDiscoveryRequest,
)

from app.mission.manager import MissionManager


router = APIRouter(
    prefix="/system",
    tags=["Mission Control"],
)


# ==================================================
# Core Services
# ==================================================

brain = SystemIntelligence()

runtime = RuntimeAdapter()

dashboard = DashboardService(
    runtime
)

scheduler = Scheduler()

# IMPORTANT:
# MissionManager uses the SAME workforce
# instance owned by RuntimeAdapter.
mission_manager = MissionManager(
    workforce=runtime.workforce,
    runtime=runtime,
)


# ==================================================
# Status
# ==================================================

@router.get(
    "/status",
    response_model=SystemStatus,
)
def status():

    data = brain.system_status()

    return SystemStatus(
        status=data.get(
            "status",
            "ONLINE",
        ),
        workers=len(
            runtime.get_workers()
        ),
        queue=runtime.get_queue_status()["pending"],
        memory=runtime.get_memory_count(),
        events=len(
            runtime.get_events()
        ),
    )


# ==================================================
# Summary
# ==================================================

@router.get(
    "/summary",
    response_model=SystemSummary,
)
def summary():

    history = runtime.get_history()

    successful = sum(
        1
        for item in history
        if item.get("status")
        in {
            "SUCCESS",
            "COMPLETED",
        }
    )

    failed = sum(
        1
        for item in history
        if item.get("status")
        == "FAILED"
    )

    return SystemSummary(
        version="0.10.0",
        uptime="Running",
        executions=len(history),
        successful=successful,
        failed=failed,
    )


# ==================================================
# Workers
# ==================================================

@router.get(
    "/workers",
    response_model=list[WorkerStatus],
)
def workers():

    return [
        WorkerStatus(**worker)
        for worker in runtime.get_workers()
    ]


# ==================================================
# Queue
# ==================================================

@router.get(
    "/queue",
    response_model=QueueStatus,
)
def queue():

    return QueueStatus(
        **runtime.get_queue_status()
    )


# ==================================================
# Memory
# ==================================================

@router.get(
    "/memory",
    response_model=MemoryStatus,
)
def memory():

    return MemoryStatus(
        items=runtime.get_memory_count()
    )


# ==================================================
# Events
# ==================================================

@router.get(
    "/events",
    response_model=list[EventStatus],
)
def events():

    return [
        EventStatus(**event)
        for event in runtime.get_event_records()
    ]


# ==================================================
# Executions
# ==================================================

@router.get(
    "/executions",
    response_model=list[ExecutionStatus],
)
def executions():

    return [
        ExecutionStatus(**item)
        for item in runtime.get_history()
    ]


# ==================================================
# Dashboard
# ==================================================

@router.get(
    "/dashboard",
)
def dashboard_summary():

    return dashboard.summary()


# ==================================================
# Generic Workflow Request
# ==================================================

@router.post(
    "/run",
    response_model=RunWorkflowResponse,
)
def run_workflow(
    request: RunWorkflowRequest,
):

    runtime.record_event(
        f"Workflow Requested: {request.workflow}",
        event_type="INFO",
        metadata={
            "workflow": request.workflow,
        },
    )

    runtime.record_execution(
        {
            "workflow": request.workflow,
            "status": "SCHEDULED",
            "duration": 0.0,
        }
    )

    return RunWorkflowResponse(
        success=True,
        status="scheduled",
        workflow=request.workflow,
    )


# ==================================================
# Product Discovery
# ==================================================

@router.post(
    "/command/run-product-discovery",
    response_model=CommandResponse,
)
def run_product_discovery(
    request: ProductDiscoveryRequest | None = None,
):

    metadata = {}

    if request and request.url:

        metadata["url"] = request.url


    mission_manager.launch(
        name="ProductDiscovery",
        objective=(
            "Discover profitable affiliate "
            "product opportunities"
        ),
        workflow="product_discovery",
        metadata=metadata,
        required_capability="product_discovery",
    )


    return CommandResponse(
        success=True,
        message=(
            "Product Discovery "
            "executed successfully"
        ),
    )


# ==================================================
# Affiliate Discovery
# ==================================================

@router.post(
    "/command/run-affiliate",
    response_model=CommandResponse,
)
def run_affiliate():

    mission_manager.launch(
        name="AffiliateDiscovery",
        objective="Analyze affiliate opportunity",
        workflow="affiliate_discovery",
        metadata={
            "url": "https://openrouter.ai"
        },
    )

    return CommandResponse(
        success=True,
        message=(
            "Workflow executed successfully"
        ),
    )