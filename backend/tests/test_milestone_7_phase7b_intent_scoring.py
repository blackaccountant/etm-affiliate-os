from datetime import datetime, timezone

import pytest

from app.audience.intent_scoring import score_intent
from app.audience.intent_scoring_contracts import INTENT_DIMENSIONS, SCORING_DIMENSIONS, IntentScoringContractError, IntentScoringInput
from app.audience.profile_contracts import AudienceProfileSummaryFact
from app.audience.qualification_contracts import DIMENSIONS, QualificationRuleset


AS_OF = datetime(2026, 8, 30, tzinfo=timezone.utc)


def ruleset(*, caps=None, weights=None, stages=None, mapping=None):
    default_weights = {key: 0 for key in DIMENSIONS}
    default_weights.update({"research_intent": 16, "comparison_intent": 16, "evaluation_intent": 16, "pricing_intent": 16, "purchase_request_intent": 16, "purchase_signal": 20})
    return QualificationRuleset(
        "m7b-v1",
        mapping or {"PROBLEM": ("problem_strength",), "INTEREST": ("interest_alignment",), "INTENT": ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent"), "PURCHASE": ("purchase_signal",), "ENGAGEMENT": ("engagement",), "BUSINESS_NEED": ("business_need_fit",)},
        stages or {"RESEARCH": 20, "COMPARE": 40, "EVALUATE": 60, "PRICING": 80, "PURCHASE_REQUEST": 100}, "MULTIPLY_CONFIDENCE_CAP",
        caps or {key: 100 for key in DIMENSIONS}, weights or default_weights,
        {key: 1 for key in DIMENSIONS}, {"NOT_QUALIFIED": 0, "EARLY": 40, "QUALIFIED": 60, "HIGH_INTENT": 80},
    )


def fact(signal_id, kind, *, topic="hosting", stage=None, strength=50, confidence=60):
    return AudienceProfileSummaryFact(signal_id, kind, topic, topic.title(), strength, confidence, AS_OF, intent_stage=stage)


def result(*facts, value_ruleset=None):
    return score_intent(IntentScoringInput(tuple(facts), AS_OF, value_ruleset or ruleset()))


def test_zero_all_signal_mappings_and_business_need_deferred():
    empty = result(); assert empty.dimensions == {key: 0 for key in SCORING_DIMENSIONS} and empty.intent_score == 0 and empty.contributions == ()
    mappings = [("PROBLEM", None, "problem_strength"), ("INTEREST", None, "interest_alignment"), ("INTENT", "RESEARCH", "research_intent"), ("INTENT", "COMPARE", "comparison_intent"), ("INTENT", "EVALUATE", "evaluation_intent"), ("INTENT", "PRICING", "pricing_intent"), ("INTENT", "PURCHASE_REQUEST", "purchase_request_intent"), ("PURCHASE", None, "purchase_signal"), ("ENGAGEMENT", None, "engagement")]
    for index, (kind, stage, dimension) in enumerate(mappings):
        scored = result(fact(str(index), kind, stage=stage, strength=100, confidence=100))
        assert scored.dimensions[dimension] > 0 and sum(value > 0 for value in scored.dimensions.values()) == 1
    assert result(fact("business", "BUSINESS_NEED", strength=100, confidence=100)).dimensions == {key: 0 for key in SCORING_DIMENSIONS}


def test_integer_arithmetic_multiplier_caps_and_intent_only_weights():
    pricing = result(fact("pricing", "INTENT", stage="PRICING", strength=51, confidence=51))
    contribution = pricing.contributions[0]
    assert contribution.confidence_adjusted_amount == 26 and contribution.final_amount == 20  # 26 * 80 // 100
    capped = result(fact("a", "PROBLEM", strength=100, confidence=100), fact("b", "PROBLEM", topic="email", strength=100, confidence=100), value_ruleset=ruleset(caps={**{key: 100 for key in DIMENSIONS}, "problem_strength": 60}))
    assert capped.dimensions["problem_strength"] == 60 and sum(item.final_amount for item in capped.contributions) == 60 and any(item.disposition == "CAPPED" for item in capped.contributions)
    diagnostic = result(fact("problem", "PROBLEM", strength=100, confidence=100)); assert diagnostic.intent_score == 0
    high = result(*(fact(str(i), "PURCHASE", topic=f"topic-{i}", strength=100, confidence=100) for i in range(3))); assert high.intent_score <= 100
    bad_weights = {key: 0 for key in DIMENSIONS}; bad_weights["problem_strength"] = 100
    with pytest.raises(IntentScoringContractError): result(value_ruleset=ruleset(weights=bad_weights))


def test_duplicates_ties_distinct_topics_conflicts_and_order_are_canonical():
    weak = fact("b", "INTENT", stage="PRICING", strength=20, confidence=100)
    strong = fact("a", "INTENT", stage="PRICING", strength=50, confidence=100)
    duplicate = result(weak, strong)
    assert duplicate.dimensions["pricing_intent"] == 40
    assert {item.disposition for item in duplicate.contributions} == {"SELECTED", "DUPLICATE_SUPPRESSED"}
    tie = result(fact("b", "PURCHASE", strength=50, confidence=100), fact("a", "PURCHASE", strength=50, confidence=100))
    assert [item.source_signal_id for item in tie.contributions if item.disposition == "SELECTED"] == ["a"]
    distinct = result(fact("a", "PROBLEM", topic="hosting", strength=50, confidence=100), fact("b", "PROBLEM", topic="email", strength=50, confidence=100))
    assert distinct.dimensions["problem_strength"] == 100
    assert result(strong, weak) == result(weak, strong)


def test_invalid_rulesets_and_no_qualification_output_or_side_effects():
    bad_stages = {"RESEARCH": 20, "COMPARE": 20, "EVALUATE": 60, "PRICING": 80, "PURCHASE_REQUEST": 100}
    with pytest.raises(IntentScoringContractError): result(value_ruleset=ruleset(stages=bad_stages))
    scored = result(fact("a", "ENGAGEMENT", strength=100, confidence=100))
    assert not hasattr(scored, "qualification_score") and not hasattr(scored, "qualification_status") and not hasattr(scored, "assessment_id")
    with pytest.raises(IntentScoringContractError): result(fact("sensitive", "PROBLEM", topic="political-news"))


def test_invalid_mapping_exact_score_maximum_and_multiplier_boundaries():
    bad_mapping = {"PROBLEM": ("pricing_intent",), "INTEREST": ("interest_alignment",), "INTENT": ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent"), "PURCHASE": ("purchase_signal",), "ENGAGEMENT": ("engagement",), "BUSINESS_NEED": ("business_need_fit",)}
    with pytest.raises(IntentScoringContractError, match="unsupported signal/dimension mapping"):
        result(fact("bad", "PROBLEM"), value_ruleset=ruleset(mapping=bad_mapping))
    boundary_stages = {"RESEARCH": 0, "COMPARE": 25, "EVALUATE": 50, "PRICING": 75, "PURCHASE_REQUEST": 100}
    zero = result(fact("zero", "INTENT", stage="RESEARCH", strength=51, confidence=51), value_ruleset=ruleset(stages=boundary_stages))
    assert zero.contributions[0].confidence_adjusted_amount == 26 and zero.contributions[0].final_amount == 0
    hundred = result(fact("hundred", "INTENT", stage="PURCHASE_REQUEST", strength=51, confidence=51), value_ruleset=ruleset(stages=boundary_stages))
    assert hundred.contributions[0].confidence_adjusted_amount == 26 and hundred.contributions[0].final_amount == 26
    maximum_weights = {key: 0 for key in DIMENSIONS}; maximum_weights["purchase_request_intent"] = 100
    maximum = result(fact("maximum", "INTENT", stage="PURCHASE_REQUEST", strength=100, confidence=100), value_ruleset=ruleset(weights=maximum_weights))
    assert maximum.dimensions["purchase_request_intent"] == 100 and maximum.intent_score == 100
    assert all(maximum.dimensions[key] == 0 for key in set(SCORING_DIMENSIONS) - {"purchase_request_intent"})
