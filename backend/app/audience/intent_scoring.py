"""Pure deterministic M7B profile intent scoring."""

from app.audience.contracts import AudienceIntentStage
from app.audience.intent_scoring_contracts import (
    INTENT_DIMENSIONS, SCORING_DIMENSIONS, IntentScoringContribution, IntentScoringContractError,
    IntentScoringInput, IntentScoringResult,
)
from app.audience.qualification_contracts import DIMENSIONS
from app.audience.safety import AudienceSafetyError, validate_audience_topic


_TYPE_DIMENSION = {"PROBLEM": "problem_strength", "INTEREST": "interest_alignment", "PURCHASE": "purchase_signal", "ENGAGEMENT": "engagement"}
_STAGE_DIMENSION = {"RESEARCH": "research_intent", "COMPARE": "comparison_intent", "EVALUATE": "evaluation_intent", "PRICING": "pricing_intent", "PURCHASE_REQUEST": "purchase_request_intent"}


def _validate_ruleset(ruleset):
    expected = {"PROBLEM": {"problem_strength"}, "INTEREST": {"interest_alignment"}, "INTENT": set(_STAGE_DIMENSION.values()), "PURCHASE": {"purchase_signal"}, "ENGAGEMENT": {"engagement"}, "BUSINESS_NEED": {"business_need_fit"}}
    if {key: set(value) for key, value in ruleset.dimension_contributions.items()} != expected:
        raise IntentScoringContractError("unsupported signal/dimension mapping")
    values = [ruleset.intent_stage_multipliers[item.value] for item in AudienceIntentStage]
    if values != sorted(values) or len(set(values)) != len(values):
        raise IntentScoringContractError("intent stage multipliers must strictly increase")
    if any(ruleset.dimension_caps[key] < 0 or ruleset.dimension_caps[key] > 100 for key in SCORING_DIMENSIONS):
        raise IntentScoringContractError("invalid dimension cap")
    if any(ruleset.intent_aggregation[key] != 0 for key in set(DIMENSIONS) - set(INTENT_DIMENSIONS)):
        raise IntentScoringContractError("diagnostic dimensions cannot affect intent score")
    if set(ruleset.intent_aggregation) != set(DIMENSIONS) or sum(ruleset.intent_aggregation[key] for key in INTENT_DIMENSIONS) != 100:
        raise IntentScoringContractError("intent weights must total 100")


def _dimension(fact):
    if fact.signal_type == "BUSINESS_NEED": return None
    if fact.signal_type == "INTENT":
        if fact.intent_stage not in _STAGE_DIMENSION: raise IntentScoringContractError("invalid intent stage")
        return _STAGE_DIMENSION[fact.intent_stage]
    if fact.intent_stage is not None or fact.signal_type not in _TYPE_DIMENSION:
        raise IntentScoringContractError("impossible signal type/stage combination")
    return _TYPE_DIMENSION[fact.signal_type]


def score_intent(value: IntentScoringInput) -> IntentScoringResult:
    if not isinstance(value, IntentScoringInput): raise IntentScoringContractError("input must be typed")
    _validate_ruleset(value.ruleset)
    candidates = []
    for fact in value.facts:
        try:
            validate_audience_topic(fact.topic)
        except AudienceSafetyError as exc:
            raise IntentScoringContractError("sensitive profile topic cannot be scored") from exc
        dimension = _dimension(fact)
        if dimension is None: continue
        adjusted = (fact.strength * fact.confidence) // 100
        multiplier = value.ruleset.intent_stage_multipliers[fact.intent_stage] if fact.signal_type == "INTENT" else 100
        pre_cap = (adjusted * multiplier) // 100
        candidates.append((fact.signal_type, fact.topic, fact.intent_stage or "", fact.id if hasattr(fact, "id") else fact.signal_id, fact, dimension, adjusted, pre_cap))
    groups = {}
    for candidate in candidates: groups.setdefault(candidate[:3], []).append(candidate)
    contributions, winners = [], []
    for group in groups.values():
        winner = sorted(group, key=lambda item: (-item[7], item[3]))[0]
        winners.append(winner)
        for item in group:
            if item is not winner:
                fact, dimension, adjusted, pre = item[4:]
                contributions.append(IntentScoringContribution(fact.signal_id, dimension, f"{value.ruleset.version}:{dimension}", fact.strength, fact.confidence, fact.strength, adjusted, 0, "DUPLICATE_SUPPRESSED", fact.topic, fact.intent_stage))
    dimensions = {key: 0 for key in SCORING_DIMENSIONS}
    for dimension in SCORING_DIMENSIONS:
        remaining = value.ruleset.dimension_caps[dimension]
        for item in sorted((item for item in winners if item[5] == dimension), key=lambda item: (item[1], item[2], item[3])):
            fact, adjusted, pre = item[4], item[6], item[7]
            final = min(pre, remaining); remaining -= final; dimensions[dimension] += final
            contributions.append(IntentScoringContribution(fact.signal_id, dimension, f"{value.ruleset.version}:{dimension}", fact.strength, fact.confidence, fact.strength, adjusted, final, "SELECTED" if final == pre else "CAPPED", fact.topic, fact.intent_stage))
    intent_score = min(100, sum(dimensions[key] * value.ruleset.intent_aggregation[key] for key in INTENT_DIMENSIONS) // 100)
    return IntentScoringResult(dimensions, intent_score, tuple(sorted(contributions, key=lambda item: (item.dimension, item.topic, item.intent_stage or "", item.source_signal_id, item.rule_id))))
