"""Durable activation for one immutable audience-signal extraction snapshot."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.audience.normalization import signal_extraction_input_fingerprint
from app.audience.signal_extraction_mission_contracts import (
    AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1,
    AudienceSignalExtractionSnapshot,
    AudienceSignalExtractionWorkflowPayload,
    audience_signal_extraction_mission_idempotency_key,
)
from app.repositories.audience_repository import AudienceRepository
from app.repositories.mission_repository import MissionRepository
from app.services.audience_foundation_service import AudienceFoundationService
from app.services.durable_operation_activation_service import (
    DurableOperationActivationService,
    SuccessorOperationSpec,
)


@dataclass(frozen=True)
class AudienceSignalExtractionLaunchResult:
    audience_research_run_id: str
    mission_id: str
    mission_status: str
    idempotency_key: str
    created: bool


class AudienceSignalExtractionMissionLaunchService:
    workflow_name = "audience_signal_extract"
    required_capability = "audience_signal_extraction"

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _research_run_key(snapshot: AudienceSignalExtractionSnapshot) -> str:
        # The fingerprint already binds observation identity; ruleset remains a
        # separate dimension and the compact digest fits the frozen 128-char key.
        return hashlib.sha256(
            f"audience-signal-extraction-run-v1\n{snapshot.observation_id}\n"
            f"{snapshot.ruleset_version}\n{snapshot.input_fingerprint}".encode("utf-8")
        ).hexdigest()

    def launch(self, observation_id: str, *, ruleset_version: str = AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1):
        db = self.session_factory()
        try:
            records = AudienceRepository(db)
            observation = records.observation(observation_id)
            if observation is None:
                raise ValueError("audience observation does not exist")
            evidence = records.evidence_for_observation(observation.id)
            fingerprint = signal_extraction_input_fingerprint(
                observation_id=observation.id,
                observation_key=observation.observation_key,
                evidence=[(item.id, item.evidence_fingerprint) for item in evidence],
            )
            snapshot = AudienceSignalExtractionSnapshot(
                observation.id, ruleset_version, fingerprint, tuple(item.id for item in evidence),
            )
            mission_key = audience_signal_extraction_mission_idempotency_key(
                snapshot.observation_id, snapshot.ruleset_version, snapshot.input_fingerprint,
            )
            activation = DurableOperationActivationService(db)
            existing_mission = MissionRepository(db).get_by_idempotency_key(mission_key)
            existing = (
                activation._existing_operation(
                    SuccessorOperationSpec("Audience signal extraction", "extract audience signals", self.workflow_name,
                                           self.required_capability, mission_key, {}),
                    existing_mission,
                )
                if existing_mission is not None else None
            )
            if existing is not None:
                run = AudienceFoundationService(db).get_or_create_research_run(
                    scope_type="audience_signal_extract", scope_reference=snapshot.observation_id,
                    idempotency_key=self._research_run_key(snapshot), metadata_json=snapshot.to_metadata(),
                )
                return AudienceSignalExtractionLaunchResult(run.id, existing.mission_id, existing.state.value, mission_key, False)
            run = AudienceFoundationService(db).get_or_create_research_run(
                scope_type="audience_signal_extract", scope_reference=snapshot.observation_id,
                idempotency_key=self._research_run_key(snapshot), metadata_json=snapshot.to_metadata(),
            )
            payload = AudienceSignalExtractionWorkflowPayload(run.id).to_dict()
            operation = activation.activate(SuccessorOperationSpec(
                "Audience signal extraction", "extract audience signals", self.workflow_name,
                self.required_capability, mission_key, payload,
            ))
            db.commit()
            return AudienceSignalExtractionLaunchResult(run.id, operation.mission_id, operation.state.value, mission_key, True)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
