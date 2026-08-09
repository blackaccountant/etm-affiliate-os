"""
System Models

Response models for ETM Affiliate OS
Mission Control API.
"""

from pydantic import BaseModel, Field


class SystemStatus(BaseModel):

    status: str
    workers: int
    queue: int
    memory: int
    events: int


class SystemSummary(BaseModel):

    version: str
    uptime: str
    executions: int
    successful: int
    failed: int


class WorkerStatus(BaseModel):

    name: str
    status: str


class QueueStatus(BaseModel):

    pending: int
    running: int
    completed: int
    failed: int


class MemoryStatus(BaseModel):

    items: int


class EventStatus(BaseModel):

    event: str
    type: str = "INFO"
    timestamp: str | None = None
    metadata: dict = Field(
        default_factory=dict
    )


class ExecutionStatus(BaseModel):

    workflow: str
    status: str
    duration: float
    timestamp: str | None = None


class RunWorkflowRequest(BaseModel):

    workflow: str
    payload: dict


class RunWorkflowResponse(BaseModel):

    success: bool
    status: str
    workflow: str


class CommandResponse(BaseModel):

    success: bool
    message: str


class ProductDiscoveryRequest(BaseModel):

    url: str | None = None