"""Launch a durable content-generation run through the frozen Mission core."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.content_intelligence.content_mission_contracts import (CONTENT_GENERATION_CAPABILITY, CONTENT_GENERATION_MISSION_NAME, CONTENT_GENERATION_WORKFLOW, ContentGenerationWorkflowPayload, content_generation_mission_idempotency_key)
from app.mission.manager import MissionManager
from app.repositories.content_generation_run_repository import ContentGenerationRunRepository
from app.repositories.mission_repository import MissionRepository


@dataclass(frozen=True)
class ContentGenerationMissionLaunchResult:
    content_generation_run_id: str
    mission_id: str
    mission_status: str
    workflow: str
    required_capability: str | None
    idempotency_key: str
    worker_name: str | None
    result_success: bool | None
    result_error: str | None
    result_data: dict[str, Any] | None = None

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if value is not None}


class ContentGenerationMissionLaunchService:
    mission_name = CONTENT_GENERATION_MISSION_NAME
    workflow_name = CONTENT_GENERATION_WORKFLOW
    required_capability = CONTENT_GENERATION_CAPABILITY
    objective = "generate and evaluate content brief"

    def __init__(self, mission_manager=None, session_factory=None):
        if mission_manager is None:
            if session_factory is None:
                raise ValueError("mission_manager or session_factory is required")
            mission_manager = MissionManager(session_factory=session_factory)
        self.mission_manager = mission_manager
        self.session_factory = session_factory or getattr(mission_manager, "session_factory", None)

    @staticmethod
    def _parse(raw):
        if raw is None or raw == "":
            return None
        if isinstance(raw, dict):
            return raw.get("data") if isinstance(raw.get("data"), dict) else raw
        try:
            parsed = json.loads(raw)
            return parsed.get("data") if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict) else parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"value": str(raw)}

    @classmethod
    def _result_from_record(cls, record, run_id):
        if record.status == "COMPLETED":
            success = True
        elif record.status == "FAILED":
            success = False
        else:
            success = None
        return ContentGenerationMissionLaunchResult(
            content_generation_run_id=run_id,
            mission_id=record.id,
            mission_status=record.status,
            workflow=record.workflow_name,
            required_capability=record.required_capability,
            idempotency_key=record.idempotency_key or content_generation_mission_idempotency_key(run_id),
            worker_name=record.current_worker_name,
            result_success=success,
            result_error=record.last_error,
            result_data=cls._parse(record.result_data),
        )

    def _existing(self, run_id, key):
        db = self.session_factory()
        try:
            record = MissionRepository(db).get_by_idempotency_key(key)
            return self._result_from_record(record, run_id) if record is not None else None
        finally:
            db.close()

    def _fresh_run(self, run_id):
        db = self.session_factory()
        try:
            run = ContentGenerationRunRepository(db).get_by_id(run_id)
            if run is None:
                raise ValueError("content generation run does not exist")
            if run.status != "CREATED":
                raise RuntimeError(f"content generation run is already {run.status.lower()}")
            return run.id
        finally:
            db.close()

    def launch(self, content_generation_run_id):
        key = content_generation_mission_idempotency_key(content_generation_run_id)
        existing = self._existing(content_generation_run_id, key)
        if existing is not None:
            return existing
        run_id = self._fresh_run(content_generation_run_id)
        metadata = ContentGenerationWorkflowPayload(run_id).to_dict()
        self.mission_manager.launch(
            name=self.mission_name,
            objective=self.objective,
            workflow=self.workflow_name,
            metadata=metadata,
            required_capability=self.required_capability,
            idempotency_key=key,
        )
        result = self._existing(run_id, key)
        if result is None:
            raise RuntimeError("durable content generation mission could not be recovered after launch")
        return result
