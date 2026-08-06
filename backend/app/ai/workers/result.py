"""
AI Worker Result

Defines the standard result returned by every AI worker.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkerResult(BaseModel):
    """
    Standard response returned by AI workers.
    """

    success: bool = True

    worker_name: str

    action: str

    message: str = ""

    data: dict[str, Any] = Field(
        default_factory=dict
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    execution_time: float = 0.0

    completed_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    error: str | None = None

    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"

        return (
            f"{status} | "
            f"{self.worker_name} | "
            f"{self.action}"
        )