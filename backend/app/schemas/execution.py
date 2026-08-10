"""
Execution Schemas

Response models for workflow and mission
execution history.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ExecutionResponse(BaseModel):

    id: int

    mission_id: Optional[str] = None

    mission_name: Optional[str] = None

    worker_name: Optional[str] = None

    workflow_name: str

    status: str

    result_data: Optional[str] = None

    started_at: Optional[datetime] = None

    completed_at: Optional[datetime] = None

    duration: float = 0.0

    retry_count: int = 0

    error: Optional[str] = None

    class Config:

        from_attributes = True