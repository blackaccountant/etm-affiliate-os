"""Pure M7C contextual qualification contracts."""
from dataclasses import dataclass
from app.audience.intent_scoring_contracts import IntentScoringContribution, IntentScoringResult
from app.audience.contracts import AudienceSubjectType
from app.audience.normalization import required_text
from app.audience.profile_contracts import AudienceProfileSummaryFact
from app.audience.qualification_contracts import QualificationContext, QualificationRuleset


class ContextualQualificationError(ValueError): pass


@dataclass(frozen=True)
class ContextualQualificationInput:
    scoring: IntentScoringResult
    facts: tuple[AudienceProfileSummaryFact, ...]
    subject_type: str
    context: QualificationContext
    ruleset: QualificationRuleset
    memberships: tuple[tuple[str, bool], ...]

    def __post_init__(self):
        if not isinstance(self.scoring, IntentScoringResult):
            raise ContextualQualificationError("M7B scoring result must be typed")
        facts = tuple(self.facts)
        if not all(isinstance(item, AudienceProfileSummaryFact) for item in facts):
            raise ContextualQualificationError("profile facts must be typed immutable summaries")
        object.__setattr__(self, "facts", facts)
        try:
            object.__setattr__(self, "subject_type", AudienceSubjectType(self.subject_type).value)
        except ValueError as exc:
            raise ContextualQualificationError("unsupported subject type") from exc
        if not isinstance(self.context, QualificationContext) or not isinstance(self.ruleset, QualificationRuleset):
            raise ContextualQualificationError("context and ruleset must be typed")
        memberships = tuple(self.memberships)
        normalized = []
        for item in memberships:
            if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[1], bool):
                raise ContextualQualificationError("memberships must contain typed revision results")
            normalized.append((required_text(item[0], "segment_revision_id"), item[1]))
        if len({item[0] for item in normalized}) != len(normalized):
            raise ContextualQualificationError("duplicate membership revision")
        object.__setattr__(self, "memberships", tuple(sorted(normalized)))


@dataclass(frozen=True)
class ContextualQualificationResult:
    business_need_fit: int
    qualification_score: int
    qualification_status: str
    gate_passed: bool
    contributions: tuple[IntentScoringContribution, ...]
