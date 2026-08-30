"""Pure M7B scoring input and result contracts; no persistence types."""

from dataclasses import dataclass
from datetime import datetime

from app.audience.normalization import aware_utc
from app.audience.profile_contracts import AudienceProfileSummaryFact
from app.audience.qualification_contracts import DIMENSIONS, QualificationRuleset


SCORING_DIMENSIONS = (
    "problem_strength", "interest_alignment", "research_intent", "comparison_intent",
    "evaluation_intent", "pricing_intent", "purchase_request_intent", "purchase_signal", "engagement",
)
INTENT_DIMENSIONS = ("research_intent", "comparison_intent", "evaluation_intent", "pricing_intent", "purchase_request_intent", "purchase_signal")


class IntentScoringContractError(ValueError):
    pass


@dataclass(frozen=True)
class IntentScoringInput:
    facts: tuple[AudienceProfileSummaryFact, ...]
    effective_as_of: datetime
    ruleset: QualificationRuleset

    def __post_init__(self):
        if not all(isinstance(item, AudienceProfileSummaryFact) for item in self.facts):
            raise IntentScoringContractError("facts must be typed immutable profile facts")
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "effective_as_of", aware_utc(self.effective_as_of, "effective_as_of"))
        if not isinstance(self.ruleset, QualificationRuleset):
            raise IntentScoringContractError("ruleset must be typed")


@dataclass(frozen=True)
class IntentScoringContribution:
    source_signal_id: str
    dimension: str
    rule_id: str
    strength: int
    confidence: int
    raw_amount: int
    confidence_adjusted_amount: int
    final_amount: int
    disposition: str
    topic: str
    intent_stage: str | None


@dataclass(frozen=True)
class IntentScoringResult:
    dimensions: dict[str, int]
    intent_score: int
    contributions: tuple[IntentScoringContribution, ...]

    def __post_init__(self):
        if set(self.dimensions) != set(SCORING_DIMENSIONS) or any(not isinstance(value, int) or not 0 <= value <= 100 for value in self.dimensions.values()):
            raise IntentScoringContractError("invalid scoring dimensions")
        if not isinstance(self.intent_score, int) or not 0 <= self.intent_score <= 100:
            raise IntentScoringContractError("invalid intent score")
