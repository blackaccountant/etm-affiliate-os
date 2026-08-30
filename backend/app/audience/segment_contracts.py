"""Small validated ALL-only rule contract for audience segment revisions."""

import hashlib
from dataclasses import dataclass

from app.audience.contracts import AudienceIntentStage, AudienceSignalType, AudienceSubjectType
from app.audience.normalization import canonical_json, normalize_topic, required_text
from app.audience.safety import AudienceSafetyError, validate_audience_topic

SEGMENT_RULESET_VERSION = "audience-segment-v1"


class AudienceSegmentContractError(ValueError):
    pass


@dataclass(frozen=True)
class AudienceSegmentSignalPredicate:
    signal_type: str
    topic: str | None = None
    intent_stage: str | None = None
    minimum_strength: int | None = None
    minimum_confidence: int | None = None
    max_age_days: int | None = None

    def __post_init__(self):
        try:
            kind = AudienceSignalType(self.signal_type).value
        except ValueError as exc:
            raise AudienceSegmentContractError("unsupported signal_type") from exc
        object.__setattr__(self, "signal_type", kind)
        if self.topic is not None:
            slug, _ = normalize_topic(self.topic, self.topic)
            try:
                object.__setattr__(self, "topic", validate_audience_topic(slug))
            except AudienceSafetyError as exc:
                raise AudienceSegmentContractError(str(exc)) from exc
        if self.intent_stage is not None:
            if kind != AudienceSignalType.INTENT.value:
                raise AudienceSegmentContractError("intent_stage is permitted only for INTENT")
            try:
                object.__setattr__(self, "intent_stage", AudienceIntentStage(self.intent_stage).value)
            except ValueError as exc:
                raise AudienceSegmentContractError("unsupported intent_stage") from exc
        for field in ("minimum_strength", "minimum_confidence"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100):
                raise AudienceSegmentContractError(f"{field} must be 0..100")
        if self.max_age_days is not None and (not isinstance(self.max_age_days, int) or isinstance(self.max_age_days, bool) or not 1 <= self.max_age_days <= 3650):
            raise AudienceSegmentContractError("max_age_days must be 1..3650")

    def to_dict(self):
        return {"signal_type": self.signal_type, "topic": self.topic, "intent_stage": self.intent_stage,
                "minimum_strength": self.minimum_strength, "minimum_confidence": self.minimum_confidence,
                "max_age_days": self.max_age_days}


@dataclass(frozen=True)
class AudienceSegmentDefinition:
    signal_predicates: tuple[AudienceSegmentSignalPredicate, ...]
    allowed_subject_types: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.signal_predicates:
            raise AudienceSegmentContractError("at least one signal predicate is required")
        predicates = tuple(self.signal_predicates)
        if not all(isinstance(item, AudienceSegmentSignalPredicate) for item in predicates):
            raise AudienceSegmentContractError("invalid signal predicate")
        types = tuple(sorted(set(AudienceSubjectType(value).value for value in self.allowed_subject_types)))
        if any(item.signal_type == AudienceSignalType.BUSINESS_NEED.value for item in predicates) and types and AudienceSubjectType.ORGANIZATION.value not in types:
            raise AudienceSegmentContractError("BUSINESS_NEED requires ORGANIZATION eligibility")
        object.__setattr__(self, "signal_predicates", predicates)
        object.__setattr__(self, "allowed_subject_types", types)

    def to_dict(self):
        return {"all_of": [item.to_dict() for item in sorted(self.signal_predicates, key=lambda item: canonical_json(item.to_dict()))],
                "allowed_subject_types": list(self.allowed_subject_types)}


def segment_definition_fingerprint(definition: AudienceSegmentDefinition, ruleset_version: object = SEGMENT_RULESET_VERSION) -> str:
    ruleset = required_text(ruleset_version, "segment_ruleset_version")
    if not isinstance(definition, AudienceSegmentDefinition):
        raise AudienceSegmentContractError("definition must be typed")
    payload = canonical_json({"ruleset": ruleset, "definition": definition.to_dict()})
    return hashlib.sha256(f"audience-segment-definition-v1\n{payload}".encode("utf-8")).hexdigest()
