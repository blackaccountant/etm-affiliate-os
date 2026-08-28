"""Bridge a durable discovery run into a mission-backed workflow launch."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.discovery.contracts import DiscoveryInputType, DiscoveryRunStatus
from app.mission.manager import MissionManager
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.mission_repository import MissionRepository


@dataclass(frozen=True)
class DiscoveryMissionLaunchResult:
    discovery_run_id: str
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
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}


class DiscoveryMissionLaunchService:
    """Validate a discovery run and launch the durable mission workflow."""

    workflow_name = "affiliate_discovery_run"
    required_capability = "affiliate_research"

    def __init__(self, mission_manager=None, session_factory=None):
        if mission_manager is None:
            if session_factory is None:
                raise ValueError("mission_manager or session_factory is required")
            mission_manager = MissionManager(session_factory=session_factory)
        self.mission_manager = mission_manager
        self.session_factory = session_factory or getattr(self.mission_manager, "session_factory", None)

    @staticmethod
    def _integer(value, *, name: str, minimum: int, maximum: int | None = None):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"invalid {name}: must be an integer")
        if value < minimum:
            raise ValueError(f"invalid {name}: must be greater than or equal to {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"invalid {name}: must be less than or equal to {maximum}")
        return value

    def _existing_mission_result(self, run_id: str):
        if self.session_factory is None:
            raise RuntimeError("session_factory is required to resolve durable missions")

        db = self.session_factory()
        try:
            record = MissionRepository(db).get_by_idempotency_key(f"affiliate-discovery-run:{run_id}")
            if record is None:
                return None
            return self._result_from_record(record)
        finally:
            db.close()

    @staticmethod
    def _parse_result_data(raw):
        if raw is None or raw == "":
            return None
        if isinstance(raw, dict):
            if "data" in raw and isinstance(raw["data"], dict):
                return raw["data"]
            return raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], dict):
                return parsed["data"]
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"value": str(raw)}

    @classmethod
    def _result_from_record(cls, record):
        metadata = cls._parse_result_data(record.input_data)
        discovery_run_id = metadata.get("discovery_run_id") if isinstance(metadata, dict) else None
        if not isinstance(discovery_run_id, str) or not discovery_run_id.strip():
            discovery_run_id = record.id

        if record.status == "COMPLETED":
            result_success = True
        elif record.status == "FAILED":
            result_success = False
        else:
            result_success = None

        return DiscoveryMissionLaunchResult(
            discovery_run_id=discovery_run_id,
            mission_id=record.id,
            mission_status=record.status,
            workflow=record.workflow_name,
            required_capability=record.required_capability,
            idempotency_key=record.idempotency_key or f"affiliate-discovery-run:{discovery_run_id}",
            worker_name=record.current_worker_name,
            result_success=result_success,
            result_error=record.last_error,
            result_data=cls._parse_result_data(record.result_data),
        )

    def _validate_policy(self, top_n, minimum_score, minimum_evidence_confidence):
        self._integer(top_n, name="top_n", minimum=1)
        self._integer(minimum_score, name="minimum_score", minimum=0, maximum=100)
        self._integer(minimum_evidence_confidence, name="minimum_evidence_confidence", minimum=0, maximum=100)

    def _resolve_run(self, discovery_run_id):
        if not isinstance(discovery_run_id, str) or not discovery_run_id.strip():
            raise ValueError("discovery run does not exist")
        if self.session_factory is None:
            raise RuntimeError("session_factory is required to resolve discovery runs")

        db = self.session_factory()
        try:
            run = DiscoveryRunRepository(db).get_by_id(discovery_run_id)
            if run is None:
                raise ValueError("discovery run does not exist")
            return run
        finally:
            db.close()

    def _new_launch_metadata(self, discovery_run_id, top_n, minimum_score, minimum_evidence_confidence):
        self._validate_policy(top_n, minimum_score, minimum_evidence_confidence)
        return {
            "discovery_run_id": discovery_run_id,
            "top_n": int(top_n),
            "minimum_score": int(minimum_score),
            "minimum_evidence_confidence": int(minimum_evidence_confidence),
        }

    def _launch_new(self, run_id, top_n, minimum_score, minimum_evidence_confidence):
        metadata = self._new_launch_metadata(run_id, top_n, minimum_score, minimum_evidence_confidence)
        idempotency_key = f"affiliate-discovery-run:{run_id}"
        launch = self.mission_manager.launch(
            name="AffiliateDiscoveryRun",
            objective=f"Execute durable affiliate discovery run {run_id}",
            workflow=self.workflow_name,
            metadata=metadata,
            required_capability=self.required_capability,
            idempotency_key=idempotency_key,
        )

        db = self.session_factory()
        try:
            record = MissionRepository(db).get_by_idempotency_key(idempotency_key)
            if record is not None:
                return self._result_from_record(record)
        finally:
            db.close()

        mission = launch.get("mission") if isinstance(launch, dict) else None
        if mission is not None and hasattr(mission, "id"):
            db = self.session_factory()
            try:
                record = MissionRepository(db).get_by_id(mission.id)
                if record is not None:
                    return self._result_from_record(record)
            finally:
                db.close()

        raise RuntimeError("durable mission record could not be recovered after launch")

    def launch(self, discovery_run_id, top_n=1, minimum_score=40, minimum_evidence_confidence=70):
        if not isinstance(discovery_run_id, str) or not discovery_run_id.strip():
            raise ValueError("discovery run does not exist")

        existing = self._existing_mission_result(discovery_run_id)
        if existing is not None:
            return existing

        run = self._resolve_run(discovery_run_id)
        if run.input_type != DiscoveryInputType.URL.value:
            raise ValueError("discovery run input_type must be URL")
        if run.status != DiscoveryRunStatus.CREATED.value:
            raise RuntimeError(f"discovery run is already {run.status.lower()}")

        return self._launch_new(run.id, top_n, minimum_score, minimum_evidence_confidence)
