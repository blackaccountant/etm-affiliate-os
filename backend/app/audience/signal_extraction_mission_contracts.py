"""Pure durable contracts for future audience-signal extraction Missions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.audience.normalization import required_text


AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND = "audience_signal_extract"
AUDIENCE_SIGNAL_EXTRACTION_MISSION_PREFIX = "audience-signal-extract"
AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1 = "audience-signal-extraction-v1"
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class AudienceSignalExtractionContractError(ValueError):
    """Typed rejection for deterministic extraction snapshot contracts."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AudienceSignalExtractionContractError("INVALID_ID", f"{field} must be a UUID")
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise AudienceSignalExtractionContractError("INVALID_ID", f"{field} must be a UUID") from error
    if str(parsed) != value.lower():
        raise AudienceSignalExtractionContractError("INVALID_ID", f"{field} must be a canonical UUID")
    return str(parsed)


def _ruleset(value: object) -> str:
    try:
        return required_text(value, "ruleset_version")
    except ValueError as error:
        raise AudienceSignalExtractionContractError("INVALID_RULESET", "ruleset_version is required") from error


def _fingerprint(value: object, field: str = "input_fingerprint") -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value.lower()):
        raise AudienceSignalExtractionContractError("INVALID_FINGERPRINT", f"{field} must be a SHA-256 hex digest")
    return value.lower()


def _evidence_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AudienceSignalExtractionContractError("INVALID_SNAPSHOT", "evidence_ids are required")
    canonical = tuple(sorted(_id(item, "evidence_id") for item in value))
    if len(set(canonical)) != len(canonical):
        raise AudienceSignalExtractionContractError("INVALID_SNAPSHOT", "evidence_ids must be unique")
    return canonical


@dataclass(frozen=True)
class AudienceSignalExtractionSnapshot:
    """JSON-safe immutable input identity for one future extraction operation."""

    observation_id: str
    ruleset_version: str
    input_fingerprint: str
    evidence_ids: tuple[str, ...]
    operation_kind: str = AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND

    def __post_init__(self):
        if self.operation_kind != AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND:
            raise AudienceSignalExtractionContractError("INVALID_SNAPSHOT", "operation_kind is invalid")
        object.__setattr__(self, "observation_id", _id(self.observation_id, "observation_id"))
        object.__setattr__(self, "ruleset_version", _ruleset(self.ruleset_version))
        object.__setattr__(self, "input_fingerprint", _fingerprint(self.input_fingerprint))
        object.__setattr__(self, "evidence_ids", _evidence_ids(self.evidence_ids))

    def to_metadata(self) -> dict[str, object]:
        return {
            "operation_kind": self.operation_kind,
            "observation_id": self.observation_id,
            "ruleset_version": self.ruleset_version,
            "input_fingerprint": self.input_fingerprint,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_metadata(cls, metadata: object) -> "AudienceSignalExtractionSnapshot":
        expected = {"operation_kind", "observation_id", "ruleset_version", "input_fingerprint", "evidence_ids"}
        if not isinstance(metadata, dict) or set(metadata) != expected:
            raise AudienceSignalExtractionContractError("INVALID_SNAPSHOT", "snapshot metadata has an invalid shape")
        return cls(
            operation_kind=metadata["operation_kind"],
            observation_id=metadata["observation_id"],
            ruleset_version=metadata["ruleset_version"],
            input_fingerprint=metadata["input_fingerprint"],
            evidence_ids=metadata["evidence_ids"],
        )


def audience_signal_extraction_mission_idempotency_key(
    observation_id: object, ruleset_version: object, input_fingerprint: object,
) -> str:
    return ":".join((
        AUDIENCE_SIGNAL_EXTRACTION_MISSION_PREFIX,
        _id(observation_id, "observation_id"),
        _ruleset(ruleset_version),
        _fingerprint(input_fingerprint),
    ))


@dataclass(frozen=True)
class AudienceSignalExtractionWorkflowPayload:
    """The future durable Mission payload: one ResearchRun UUID only."""

    audience_research_run_id: str

    def __post_init__(self):
        object.__setattr__(self, "audience_research_run_id", _id(self.audience_research_run_id, "audience_research_run_id"))

    def to_dict(self) -> dict[str, str]:
        return {"audience_research_run_id": self.audience_research_run_id}

    @classmethod
    def from_payload(cls, payload: object) -> "AudienceSignalExtractionWorkflowPayload":
        if not isinstance(payload, dict) or set(payload) != {"audience_research_run_id"}:
            raise AudienceSignalExtractionContractError("INVALID_PAYLOAD", "workflow payload must contain only audience_research_run_id")
        return cls(payload["audience_research_run_id"])
