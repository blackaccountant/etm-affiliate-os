"""Provider-free structured interpretation for the initial audience ruleset."""

from __future__ import annotations

from dataclasses import dataclass

from app.audience.signal_extraction_mission_contracts import (
    AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1,
    AudienceSignalExtractionContractError,
)
from app.services.audience_signal_service import SignalCandidate


@dataclass(frozen=True)
class ExtractionObservationFact:
    normalized_fact: object
    subject_type: str | None = None


@dataclass(frozen=True)
class ExtractionEvidenceFact:
    evidence_id: str
    normalized_representation: object


_RULES = {
    "pricing": ("INTENT", "PRICING", "pricing", "Pricing"),
    "compare": ("INTENT", "COMPARE", "comparison", "Comparison"),
    "comparison": ("INTENT", "COMPARE", "comparison", "Comparison"),
    "purchase_request": ("INTENT", "PURCHASE_REQUEST", "purchase-request", "Purchase request"),
    "engagement": ("ENGAGEMENT", None, "engagement", "Engagement"),
    "business_need": ("BUSINESS_NEED", None, "business-need", "Business need"),
}


def _structured_event(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    event = value.get("event")
    return event.strip().lower() if isinstance(event, str) else None


def extract(
    observation_fact: ExtractionObservationFact,
    evidence_facts: list[ExtractionEvidenceFact] | tuple[ExtractionEvidenceFact, ...],
    *,
    ruleset_version: str,
) -> list[SignalCandidate]:
    """Return deduplicated candidates from explicit normalized event markers only."""
    if ruleset_version != AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1:
        raise AudienceSignalExtractionContractError("UNSUPPORTED_RULESET", "ruleset_version is unsupported")
    if not isinstance(observation_fact, ExtractionObservationFact):
        raise AudienceSignalExtractionContractError("INVALID_INPUT", "observation_fact is invalid")
    if not isinstance(evidence_facts, (list, tuple)) or not all(isinstance(item, ExtractionEvidenceFact) for item in evidence_facts):
        raise AudienceSignalExtractionContractError("INVALID_INPUT", "evidence_facts are invalid")

    evidence_ids = sorted(item.evidence_id for item in evidence_facts)
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        raise AudienceSignalExtractionContractError("INVALID_INPUT", "evidence_ids must be nonempty and unique")

    events = {_structured_event(observation_fact.normalized_fact)}
    events.update(_structured_event(item.normalized_representation) for item in evidence_facts)
    candidates: dict[tuple[str, str, str | None], SignalCandidate] = {}
    for event in sorted(event for event in events if event in _RULES):
        signal_type, intent_stage, topic, topic_label = _RULES[event]
        if signal_type == "BUSINESS_NEED" and observation_fact.subject_type not in {None, "ORGANIZATION"}:
            continue
        key = (signal_type, topic, intent_stage)
        candidates[key] = SignalCandidate(
            signal_type=signal_type,
            topic=topic,
            topic_label=topic_label,
            intent_stage=intent_stage,
            strength=50,
            confidence=60,
            evidence_ids=evidence_ids,
            ruleset_version=ruleset_version,
            rationale=f"Deterministic {event} event marker.",
            metadata_json={"extraction_rule": event},
        )
    return [candidates[key] for key in sorted(candidates)]
