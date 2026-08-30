"""Caller-owned immutable segment-membership evaluation."""

from dataclasses import dataclass
from datetime import datetime

from app.audience.profile_contracts import PROFILE_RULESET_VERSION, AudienceProfileSummaryFact
from app.audience.segment_contracts import SEGMENT_RULESET_VERSION, AudienceSegmentDefinition, AudienceSegmentSignalPredicate, segment_definition_fingerprint
from app.audience.segment_evaluation import evaluates_to_member
from app.models.audience import AudienceProfile, AudienceSegmentMembership, AudienceSubject
from app.repositories.audience_profile_repository import AudienceProfileRepository
from app.repositories.audience_segment_membership_repository import AudienceSegmentMembershipRepository
from app.repositories.audience_segment_repository import AudienceSegmentRepository


class AudienceSegmentMembershipError(ValueError):
    def __init__(self, category, message):
        super().__init__(message); self.category = category


@dataclass(frozen=True)
class AudienceSegmentMembershipResult:
    membership_id: str
    segment_revision_id: str
    profile_id: str
    is_member: bool


class AudienceSegmentMembershipService:
    def __init__(self, db):
        self.db = db; self.profiles = AudienceProfileRepository(db)
        self.segments = AudienceSegmentRepository(db); self.memberships = AudienceSegmentMembershipRepository(db)

    def _facts(self, profile):
        if profile.profile_ruleset_version != PROFILE_RULESET_VERSION:
            raise AudienceSegmentMembershipError("UNSUPPORTED_PROFILE_RULESET", "unsupported profile ruleset")
        try:
            categories = profile.summary_json["categories"]
            def parse(item):
                value = dict(item)
                value["observed_at"] = datetime.fromisoformat(value["observed_at"])
                if value.get("expires_at") is not None: value["expires_at"] = datetime.fromisoformat(value["expires_at"])
                return AudienceProfileSummaryFact(**value)
            facts = tuple(parse(item) for category, items in categories.items() for item in items if category == item.get("signal_type"))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AudienceSegmentMembershipError("MALFORMED_PROFILE_SUMMARY", "invalid profile summary") from exc
        if sum(len(items) for items in categories.values()) != len(facts) or {fact.signal_id for fact in facts} != set(self.profiles.list_signal_ids(profile.id)):
            raise AudienceSegmentMembershipError("MALFORMED_PROFILE_SUMMARY", "profile summary/source junction mismatch")
        return facts

    def _definition(self, revision):
        if revision.segment_ruleset_version != SEGMENT_RULESET_VERSION:
            raise AudienceSegmentMembershipError("UNSUPPORTED_SEGMENT_RULESET", "unsupported segment ruleset")
        try:
            definition = AudienceSegmentDefinition(tuple(AudienceSegmentSignalPredicate(**item) for item in revision.definition_json["all_of"]), tuple(revision.definition_json.get("allowed_subject_types", ())))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AudienceSegmentMembershipError("MALFORMED_SEGMENT_REVISION", "invalid segment definition") from exc
        if segment_definition_fingerprint(definition, revision.segment_ruleset_version) != revision.definition_fingerprint:
            raise AudienceSegmentMembershipError("DEFINITION_FINGERPRINT_MISMATCH", "segment definition fingerprint mismatch")
        return definition

    def evaluate(self, profile_id, segment_revision_id):
        profile = self.profiles.get_by_id(profile_id)
        revision = self.segments.get_revision_by_id(segment_revision_id)
        if profile is None: raise AudienceSegmentMembershipError("PROFILE_NOT_FOUND", "audience profile does not exist")
        if revision is None: raise AudienceSegmentMembershipError("SEGMENT_REVISION_NOT_FOUND", "segment revision does not exist")
        subject = self.db.get(AudienceSubject, profile.subject_id)
        if subject is None: raise AudienceSegmentMembershipError("MALFORMED_PROFILE_SUMMARY", "profile subject does not exist")
        result = evaluates_to_member(self._definition(revision), self._facts(profile), subject_type=subject.subject_type, effective_as_of=profile.effective_as_of)
        try:
            stored = self.memberships.create_or_reuse(AudienceSegmentMembership(segment_revision_id=revision.id, profile_id=profile.id, is_member=result))
        except ValueError as exc:
            raise AudienceSegmentMembershipError("IMMUTABLE_MEMBERSHIP_CONFLICT", str(exc)) from exc
        return AudienceSegmentMembershipResult(stored.id, revision.id, profile.id, stored.is_member)
