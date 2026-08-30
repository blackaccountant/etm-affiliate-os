"""Typed, deterministic contracts for immutable audience profile snapshots."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.audience.contracts import AudienceIntentStage, AudienceSignalType
from app.audience.normalization import aware_utc, canonical_json, required_text

PROFILE_RULESET_VERSION = "audience-profile-v1"


class AudienceProfileContractError(ValueError):
    pass


def profile_source_fingerprint(subject_id: object, profile_ruleset_version: object,
                               signal_identities: list[tuple[object, object]]) -> str:
    subject = required_text(subject_id, "subject_id")
    ruleset = required_text(profile_ruleset_version, "profile_ruleset_version")
    entries = [f"{required_text(signal_id, 'signal_id')}:{required_text(key, 'extraction_key')}"
               for signal_id, key in signal_identities]
    ids = [entry.split(":", 1)[0] for entry in entries]
    if len(set(ids)) != len(ids):
        raise AudienceProfileContractError("duplicate signal_id in profile source")
    payload = canonical_json({"subject_id": subject, "ruleset": ruleset, "signals": sorted(entries)})
    return hashlib.sha256(f"audience-profile-source-v1\n{payload}".encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AudienceProfileSummaryFact:
    signal_id: str
    signal_type: str
    topic: str
    topic_label: str
    strength: int
    confidence: int
    observed_at: datetime
    expires_at: datetime | None = None
    intent_stage: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "signal_id", required_text(self.signal_id, "signal_id"))
        try:
            object.__setattr__(self, "signal_type", AudienceSignalType(self.signal_type).value)
        except ValueError as exc:
            raise AudienceProfileContractError("unsupported signal_type") from exc
        if self.intent_stage is not None:
            if self.signal_type != AudienceSignalType.INTENT.value:
                raise AudienceProfileContractError("intent_stage is permitted only for INTENT")
            try:
                object.__setattr__(self, "intent_stage", AudienceIntentStage(self.intent_stage).value)
            except ValueError as exc:
                raise AudienceProfileContractError("unsupported intent_stage") from exc
        if not all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100 for value in (self.strength, self.confidence)):
            raise AudienceProfileContractError("strength and confidence must be 0..100")
        object.__setattr__(self, "topic", required_text(self.topic, "topic", lowercase=True))
        object.__setattr__(self, "topic_label", required_text(self.topic_label, "topic_label"))
        object.__setattr__(self, "observed_at", aware_utc(self.observed_at, "observed_at"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", aware_utc(self.expires_at, "expires_at"))

    def to_dict(self):
        return {"signal_id": self.signal_id, "signal_type": self.signal_type, "topic": self.topic,
                "topic_label": self.topic_label, "intent_stage": self.intent_stage,
                "strength": self.strength, "confidence": self.confidence,
                "observed_at": self.observed_at.isoformat(),
                "expires_at": self.expires_at.isoformat() if self.expires_at else None}
