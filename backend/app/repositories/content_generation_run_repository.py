"""Repository for durable content generation attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.content_generation_run import ContentGenerationRun


class ContentGenerationRunRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def create(self, *, content_brief_id: str, provider: str, model: str, prompt_version: str,
               generation_parameters: dict | None = None, status: str = "CREATED",
               idempotency_key: str | None = None, attempt_count: int = 0,
               result_summary: str | None = None, error_summary: str | None = None) -> ContentGenerationRun:
        run = ContentGenerationRun(
            id=str(uuid4()),
            content_brief_id=content_brief_id,
            idempotency_key=idempotency_key or str(uuid4()),
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            generation_parameters=generation_parameters,
            status=status,
            attempt_count=attempt_count,
            result_summary=result_summary,
            error_summary=error_summary,
            started_at=self._utc_now(),
            completed_at=None,
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get_by_id(self, run_id: str) -> ContentGenerationRun | None:
        return self.db.get(ContentGenerationRun, run_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> ContentGenerationRun | None:
        return self.db.query(ContentGenerationRun).filter(ContentGenerationRun.idempotency_key == idempotency_key).first()
