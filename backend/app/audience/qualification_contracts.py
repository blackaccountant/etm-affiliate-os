"""Typed, deterministic contracts for immutable M7 qualification assessments."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
from typing import Mapping

from app.audience.contracts import AudienceIntentStage, AudienceSignalType
from app.audience.normalization import aware_utc, canonical_json, normalize_topic, required_text
from app.audience.safety import AudienceSafetyError, validate_audience_topic


DIMENSIONS = (
    "problem_strength", "interest_alignment", "research_intent", "comparison_intent",
    "evaluation_intent", "pricing_intent", "purchase_request_intent", "purchase_signal",
    "engagement", "business_need_fit",
)


class QualificationContextKind(str, Enum):
    NONE = "NONE"
    PRODUCT = "PRODUCT"
    OFFER = "OFFER"
    TOPIC = "TOPIC"


class QualificationStatus(str, Enum):
    NOT_QUALIFIED = "NOT_QUALIFIED"
    EARLY = "EARLY"
    QUALIFIED = "QUALIFIED"
    HIGH_INTENT = "HIGH_INTENT"


class ContributionDisposition(str, Enum):
    SELECTED = "SELECTED"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    CAPPED = "CAPPED"


class AudienceQualificationContractError(ValueError):
    pass


def _fingerprint(namespace: str, value: object) -> str:
    return hashlib.sha256(f"{namespace}\n{canonical_json(value)}".encode("utf-8")).hexdigest()


def _score(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise AudienceQualificationContractError(f"{field} must be 0..100")
    return value


@dataclass(frozen=True)
class QualificationContext:
    kind: str
    context_id: str | None = None
    topic: str | None = None

    def __post_init__(self):
        try:
            kind = QualificationContextKind(self.kind).value
        except ValueError as exc:
            raise AudienceQualificationContractError("unsupported context kind") from exc
        object.__setattr__(self, "kind", kind)
        if kind == QualificationContextKind.NONE.value:
            if self.context_id is not None or self.topic is not None:
                raise AudienceQualificationContractError("NONE context must be empty")
        elif kind == QualificationContextKind.TOPIC.value:
            if self.context_id is not None or self.topic is None:
                raise AudienceQualificationContractError("TOPIC context requires only topic")
        elif self.context_id is None:
            raise AudienceQualificationContractError("PRODUCT/OFFER context requires durable ID")
        if self.context_id is not None:
            object.__setattr__(self, "context_id", required_text(self.context_id, "context_id"))
        if self.topic is not None:
            topic, _ = normalize_topic(self.topic, self.topic)
            try:
                object.__setattr__(self, "topic", validate_audience_topic(topic))
            except AudienceSafetyError as exc:
                raise AudienceQualificationContractError(str(exc)) from exc

    def to_dict(self):
        return {"kind": self.kind, "context_id": self.context_id, "topic": self.topic}


def context_fingerprint(context: QualificationContext) -> str:
    if not isinstance(context, QualificationContext):
        raise AudienceQualificationContractError("context must be typed")
    return _fingerprint("audience-qualification-context-v1", context.to_dict())


def selected_membership_fingerprint(membership_ids) -> str:
    ids = tuple(required_text(value, "membership_id") for value in membership_ids)
    if len(ids) != len(set(ids)):
        raise AudienceQualificationContractError("duplicate membership IDs")
    return _fingerprint("audience-qualification-memberships-v1", sorted(ids))


@dataclass(frozen=True)
class QualificationRuleset:
    version: str
    dimension_contributions: Mapping[str, tuple[str, ...]]
    intent_stage_multipliers: Mapping[str, int]
    strength_confidence_policy: str
    dimension_caps: Mapping[str, int]
    intent_aggregation: Mapping[str, int]
    qualification_aggregation: Mapping[str, int]
    thresholds: Mapping[str, int]
    required_segment_revision_ids: tuple[str, ...] = ()
    topic_alignment_required: bool = False

    def __post_init__(self):
        object.__setattr__(self, "version", required_text(self.version, "ruleset_version"))
        if self.strength_confidence_policy != "MULTIPLY_CONFIDENCE_CAP":
            raise AudienceQualificationContractError("unsupported strength/confidence policy")
        expected_types = {item.value for item in AudienceSignalType}
        if set(self.dimension_contributions) != expected_types:
            raise AudienceQualificationContractError("dimension contributions must cover exactly all signal types")
        normalized_contributions = {}
        for signal_type, dimensions in self.dimension_contributions.items():
            try:
                AudienceSignalType(signal_type)
            except ValueError as exc:
                raise AudienceQualificationContractError("unsupported contribution signal type") from exc
            values = tuple(dimensions)
            if not values or any(value not in DIMENSIONS for value in values):
                raise AudienceQualificationContractError("invalid contribution dimension")
            normalized_contributions[signal_type] = tuple(sorted(set(values)))
        object.__setattr__(self, "dimension_contributions", normalized_contributions)
        if set(self.intent_stage_multipliers) != {item.value for item in AudienceIntentStage}:
            raise AudienceQualificationContractError("intent stages must be complete")
        object.__setattr__(self, "intent_stage_multipliers", {key: _score(value, key) for key, value in self.intent_stage_multipliers.items()})
        if set(self.dimension_caps) != set(DIMENSIONS):
            raise AudienceQualificationContractError("dimension caps must be complete")
        object.__setattr__(self, "dimension_caps", {key: _score(value, key) for key, value in self.dimension_caps.items()})
        for field in ("intent_aggregation", "qualification_aggregation"):
            values = getattr(self, field)
            if not values or any(key not in DIMENSIONS or not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100 for key, value in values.items()):
                raise AudienceQualificationContractError(f"invalid {field}")
            object.__setattr__(self, field, dict(values))
        required_statuses = [item.value for item in QualificationStatus]
        if set(self.thresholds) != set(required_statuses):
            raise AudienceQualificationContractError("qualification thresholds must be complete")
        threshold_values = [_score(self.thresholds[item], item) for item in required_statuses]
        if threshold_values[0] != 0 or threshold_values != sorted(threshold_values):
            raise AudienceQualificationContractError("qualification thresholds must be ordered from zero")
        object.__setattr__(self, "thresholds", dict(zip(required_statuses, threshold_values)))
        revision_ids = tuple(required_text(value, "segment_revision_id") for value in self.required_segment_revision_ids)
        if len(revision_ids) != len(set(revision_ids)):
            raise AudienceQualificationContractError("duplicate required segment revision")
        object.__setattr__(self, "required_segment_revision_ids", tuple(sorted(revision_ids)))
        if not isinstance(self.topic_alignment_required, bool):
            raise AudienceQualificationContractError("topic_alignment_required must be bool")

    def to_dict(self):
        return {
            "version": self.version,
            "dimension_contributions": {key: list(self.dimension_contributions[key]) for key in sorted(self.dimension_contributions)},
            "intent_stage_multipliers": dict(sorted(self.intent_stage_multipliers.items())),
            "strength_confidence_policy": self.strength_confidence_policy,
            "dimension_caps": dict(sorted(self.dimension_caps.items())),
            "intent_aggregation": dict(sorted(self.intent_aggregation.items())),
            "qualification_aggregation": dict(sorted(self.qualification_aggregation.items())),
            "thresholds": dict(sorted(self.thresholds.items())),
            "required_segment_revision_ids": list(self.required_segment_revision_ids),
            "topic_alignment_required": self.topic_alignment_required,
        }


def qualification_ruleset_fingerprint(ruleset: QualificationRuleset) -> str:
    if not isinstance(ruleset, QualificationRuleset):
        raise AudienceQualificationContractError("ruleset must be typed")
    return _fingerprint("audience-qualification-ruleset-v1", ruleset.to_dict())


@dataclass(frozen=True)
class QualificationContributionInput:
    source_signal_id: str
    dimension: str
    rule_id: str
    strength: int
    confidence: int
    raw_amount: int
    confidence_adjusted_amount: int
    final_amount: int
    disposition: str

    def __post_init__(self):
        object.__setattr__(self, "source_signal_id", required_text(self.source_signal_id, "source_signal_id"))
        if self.dimension not in DIMENSIONS:
            raise AudienceQualificationContractError("invalid contribution dimension")
        object.__setattr__(self, "rule_id", required_text(self.rule_id, "rule_id"))
        for field in ("strength", "confidence", "raw_amount", "confidence_adjusted_amount", "final_amount"):
            object.__setattr__(self, field, _score(getattr(self, field), field))
        try:
            object.__setattr__(self, "disposition", ContributionDisposition(self.disposition).value)
        except ValueError as exc:
            raise AudienceQualificationContractError("invalid contribution disposition") from exc

    def to_dict(self):
        return self.__dict__.copy()


@dataclass(frozen=True)
class QualificationAssessmentInput:
    profile_id: str
    ruleset: QualificationRuleset
    context: QualificationContext
    membership_ids: tuple[str, ...]
    dimensions: Mapping[str, int]
    intent_score: int
    qualification_score: int
    qualification_status: str
    derived_at: datetime
    contributions: tuple[QualificationContributionInput, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "profile_id", required_text(self.profile_id, "profile_id"))
        if not isinstance(self.ruleset, QualificationRuleset) or not isinstance(self.context, QualificationContext):
            raise AudienceQualificationContractError("ruleset and context must be typed")
        ids = tuple(required_text(value, "membership_id") for value in self.membership_ids)
        if len(ids) != len(set(ids)):
            raise AudienceQualificationContractError("duplicate membership IDs")
        object.__setattr__(self, "membership_ids", tuple(sorted(ids)))
        if set(self.dimensions) != set(DIMENSIONS):
            raise AudienceQualificationContractError("assessment dimensions must be complete")
        object.__setattr__(self, "dimensions", {key: _score(value, key) for key, value in self.dimensions.items()})
        object.__setattr__(self, "intent_score", _score(self.intent_score, "intent_score"))
        object.__setattr__(self, "qualification_score", _score(self.qualification_score, "qualification_score"))
        try:
            object.__setattr__(self, "qualification_status", QualificationStatus(self.qualification_status).value)
        except ValueError as exc:
            raise AudienceQualificationContractError("invalid qualification status") from exc
        object.__setattr__(self, "derived_at", aware_utc(self.derived_at, "derived_at"))
        values = tuple(self.contributions)
        if not all(isinstance(value, QualificationContributionInput) for value in values):
            raise AudienceQualificationContractError("contributions must be typed")
        identities = [(item.source_signal_id, item.dimension, item.rule_id) for item in values]
        if len(identities) != len(set(identities)):
            raise AudienceQualificationContractError("duplicate contribution identity")
        object.__setattr__(self, "contributions", tuple(sorted(values, key=lambda item: (item.source_signal_id, item.dimension, item.rule_id))))
