"""Pure deterministic M7C contextual qualification; no persistence."""
from app.audience.contextual_qualification_contracts import ContextualQualificationError, ContextualQualificationInput, ContextualQualificationResult
from app.audience.intent_scoring_contracts import IntentScoringContribution
from app.audience.qualification_contracts import DIMENSIONS, QualificationStatus


def qualify_contextually(value: ContextualQualificationInput) -> ContextualQualificationResult:
    if not isinstance(value, ContextualQualificationInput): raise ContextualQualificationError("typed input required")
    weights = value.ruleset.qualification_aggregation
    if set(weights) != set(DIMENSIONS) or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in weights.values()) or sum(weights.values()) != 100:
        raise ContextualQualificationError("qualification weights must total 100")
    context_topic = value.context.topic
    candidates = []
    if value.subject_type == "ORGANIZATION" and context_topic is not None:
        for fact in value.facts:
            if fact.signal_type == "BUSINESS_NEED" and fact.topic == context_topic:
                adjusted = (fact.strength * fact.confidence) // 100
                candidates.append((fact.topic, fact.intent_stage or "", fact.signal_id, fact, adjusted))
    winners, contributions, remaining = [], [], value.ruleset.dimension_caps["business_need_fit"]
    groups = {}
    for item in candidates: groups.setdefault(("BUSINESS_NEED", item[0], item[1]), []).append(item)
    for group in groups.values():
        winner = sorted(group, key=lambda item: (-item[4], item[2]))[0]; winners.append(winner)
        for item in group:
            if item is not winner:
                fact = item[3]; contributions.append(IntentScoringContribution(fact.signal_id, "business_need_fit", f"{value.ruleset.version}:business_need_fit", fact.strength, fact.confidence, fact.strength, item[4], 0, "DUPLICATE_SUPPRESSED", fact.topic, fact.intent_stage))
    for item in sorted(winners, key=lambda item: (item[0], item[1], item[2])):
        fact, amount = item[3], item[4]; final = min(amount, remaining); remaining -= final
        contributions.append(IntentScoringContribution(fact.signal_id, "business_need_fit", f"{value.ruleset.version}:business_need_fit", fact.strength, fact.confidence, fact.strength, amount, final, "SELECTED" if final == amount else "CAPPED", fact.topic, fact.intent_stage))
    business_need_fit = sum(item.final_amount for item in contributions)
    dimensions = {**value.scoring.dimensions, "business_need_fit": business_need_fit}
    score = min(100, sum(dimensions[key] * weights[key] for key in DIMENSIONS) // 100)
    gate_passed = all(any(revision == required and member for revision, member in value.memberships) for required in value.ruleset.required_segment_revision_ids)
    status = QualificationStatus.NOT_QUALIFIED.value if not gate_passed else max((status for status, threshold in value.ruleset.thresholds.items() if score >= threshold), key=lambda status: value.ruleset.thresholds[status])
    return ContextualQualificationResult(business_need_fit, score, status, gate_passed, tuple(sorted(contributions, key=lambda item: (item.topic, item.intent_stage or "", item.source_signal_id))))
