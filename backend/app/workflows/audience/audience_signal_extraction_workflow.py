"""Fresh-session replay of a durable audience signal extraction snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.audience.deterministic_signal_extractor import (
    ExtractionEvidenceFact,
    ExtractionObservationFact,
    extract,
)
from app.audience.normalization import signal_extraction_input_fingerprint
from app.audience.signal_extraction_mission_contracts import (
    AudienceSignalExtractionContractError,
    AudienceSignalExtractionSnapshot,
    AudienceSignalExtractionWorkflowPayload,
)
from app.database.session import SessionLocal
from app.repositories.audience_repository import AudienceRepository
from app.repositories.execution_repository import ExecutionLeaseLostError, ExecutionRepository
from app.services.audience_signal_service import AudienceSignalService
from app.services.execution_runtime_context import current_execution_runtime_context
from app.workflow_engine.workflow_result import WorkflowResult


@dataclass(frozen=True)
class AudienceSignalExtractionWorkflowResult:
    research_run_id: str
    observation_id: str
    ruleset_version: str
    input_fingerprint: str
    candidate_count: int
    signal_ids: tuple[str, ...]

    def to_dict(self):
        return asdict(self) | {"signal_ids": list(self.signal_ids)}


class AudienceSignalExtractionWorkflow:
    workflow_name = "audience_signal_extract"

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    @staticmethod
    def _failure(values, error):
        data = {"audience_research_run_id": values.audience_research_run_id} if values else {}
        return WorkflowResult(success=False, workflow=AudienceSignalExtractionWorkflow.workflow_name, data=data,
                              errors=[f"validation error: {error}"])

    def execute(self, payload):
        try:
            values = AudienceSignalExtractionWorkflowPayload.from_payload(payload)
        except AudienceSignalExtractionContractError as error:
            return self._failure(None, str(error))
        db = self.session_factory()
        try:
            records = AudienceRepository(db)
            run = records.research_run(values.audience_research_run_id)
            if run is None:
                return self._failure(values, "audience research run does not exist")
            snapshot = AudienceSignalExtractionSnapshot.from_metadata(run.metadata_json)
            observation = records.observation(snapshot.observation_id)
            evidence = records.evidence_for_snapshot(snapshot.observation_id, snapshot.evidence_ids)
            if observation is None or len(evidence) != len(snapshot.evidence_ids):
                return self._failure(values, "snapshotted audience input is missing")
            fingerprint = signal_extraction_input_fingerprint(
                observation_id=observation.id, observation_key=observation.observation_key,
                evidence=[(item.id, item.evidence_fingerprint) for item in evidence],
            )
            if fingerprint != snapshot.input_fingerprint:
                return self._failure(values, "audience extraction snapshot fingerprint mismatch")
            subject = records.subject(observation.subject_id) if observation.subject_id else None
            candidates = extract(
                ExtractionObservationFact(observation.normalized_fact, subject.subject_type if subject else None),
                [ExtractionEvidenceFact(item.id, item.normalized_representation) for item in evidence],
                ruleset_version=snapshot.ruleset_version,
            )
            context = current_execution_runtime_context()
            if context is None:
                return self._failure(values, "execution authority is required")
            ExecutionRepository(db).verify_active_authority(context.authority)
            service = AudienceSignalService(db)
            signals = [service.persist(candidate, subject_id=observation.subject_id) for candidate in candidates]
            db.commit()
            result = AudienceSignalExtractionWorkflowResult(
                run.id, observation.id, snapshot.ruleset_version, snapshot.input_fingerprint,
                len(candidates), tuple(sorted(signal.id for signal in signals)),
            )
            return WorkflowResult(success=True, workflow=self.workflow_name, data=result.to_dict(), errors=[])
        except ExecutionLeaseLostError:
            db.rollback()
            raise
        except AudienceSignalExtractionContractError as error:
            db.rollback()
            return self._failure(values, str(error))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
