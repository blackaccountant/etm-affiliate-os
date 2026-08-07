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

from app.executor.executor import TaskExecutor

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
)


router = APIRouter(
    prefix="/system",
    tags=["Mission Control"],
)


brain = SystemIntelligence()

runtime = RuntimeAdapter()

dashboard = DashboardService(runtime)

scheduler = Scheduler()

executor = TaskExecutor(
    runtime=runtime
)


# --------------------------------------------------
# Status
# --------------------------------------------------

@router.get(
    "/status",
    response_model=SystemStatus,
)
def status():

    data = brain.system_status()

    return SystemStatus(
        status=data.get("status", "ONLINE"),
        workers=1,
        queue=runtime.get_queue_status()["pending"],
        memory=runtime.get_memory_count(),
        events=len(runtime.get_events()),
    )


# --------------------------------------------------
# Summary
# --------------------------------------------------

@router.get(
    "/summary",
    response_model=SystemSummary,
)
def summary():

    return SystemSummary(
        version="0.10.0",
        uptime="Running",
        executions=len(runtime.get_history()),
        successful=0,
        failed=0,
    )


# --------------------------------------------------
# Workers
# --------------------------------------------------

@router.get(
    "/workers",
    response_model=list[WorkerStatus],
)
def workers():

    return [
        WorkerStatus(**worker)
        for worker in runtime.get_workers()
    ]


# --------------------------------------------------
# Queue
# --------------------------------------------------

@router.get(
    "/queue",
    response_model=QueueStatus,
)
def queue():

    return QueueStatus(
        **runtime.get_queue_status()
    )


# --------------------------------------------------
# Memory
# --------------------------------------------------

@router.get(
    "/memory",
    response_model=MemoryStatus,
)
def memory():

    return MemoryStatus(
        items=runtime.get_memory_count()
    )


# --------------------------------------------------
# Events
# --------------------------------------------------

@router.get(
    "/events",
    response_model=list[EventStatus],
)
def events():

    return [
        EventStatus(event=event)
        for event in runtime.get_events()
    ]


# --------------------------------------------------
# Executions
# --------------------------------------------------

@router.get(
    "/executions",
    response_model=list[ExecutionStatus],
)
def executions():

    return [
        ExecutionStatus(**item)
        for item in runtime.get_history()
    ]


# --------------------------------------------------
# Dashboard
# --------------------------------------------------

@router.get(
    "/dashboard",
)
def dashboard_summary():

    return dashboard.summary()


# --------------------------------------------------
# Run Workflow
# --------------------------------------------------

@router.post(
    "/run",
    response_model=RunWorkflowResponse,
)
def run_workflow(
    request: RunWorkflowRequest,
):

    runtime.record_event(
        f"Workflow Requested: {request.workflow}"
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


# --------------------------------------------------
# Command Center
# --------------------------------------------------

@router.post(
    "/command/run-affiliate",
    response_model=CommandResponse,
)
def run_affiliate():

    task = scheduler.schedule(
        workflow_name="affiliate_discovery",
        payload={
            "url": "https://openrouter.ai"
        },
    )


    runtime.record_event(
        "Affiliate Discovery Scheduled"
    )


    runtime.record_execution(
        {
            "workflow": "affiliate_discovery",
            "status": "SCHEDULED",
            "duration": 0.0,
        }
    )


    result = executor.execute(task)


    runtime.record_event(
        "Affiliate Discovery Completed"
    )


    runtime.record_execution(
        {
            "workflow": "affiliate_discovery",
            "status": "SUCCESS",
            "duration": 0.0,
        }
    )


    return CommandResponse(
        success=True,
        message="Workflow executed successfully",
    )