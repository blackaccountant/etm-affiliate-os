"""
AI Worker Task

Defines a standard task object that every AI worker
receives before executing work.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkerTask(BaseModel):
    """
    Standard task model for all AI workers.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    worker_name: str

    action: str

    payload: dict[str, Any] = Field(
        default_factory=dict
    )

    priority: int = Field(
        default=5,
        ge=1,
        le=10,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    def __str__(self) -> str:
        return (
            f"{self.worker_name} | "
            f"{self.action} | "
            f"Priority {self.priority}"
        )