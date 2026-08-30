"""Pure deterministic evaluation of immutable profile facts against segment rules."""

from app.audience.normalization import aware_utc


def _matches(predicate, fact, effective_as_of):
    if fact.signal_type != predicate.signal_type:
        return False
    if predicate.topic is not None and fact.topic != predicate.topic:
        return False
    if predicate.intent_stage is not None and fact.intent_stage != predicate.intent_stage:
        return False
    if predicate.minimum_strength is not None and fact.strength < predicate.minimum_strength:
        return False
    if predicate.minimum_confidence is not None and fact.confidence < predicate.minimum_confidence:
        return False
    if predicate.max_age_days is not None:
        age = aware_utc(effective_as_of, "effective_as_of") - aware_utc(fact.observed_at, "observed_at")
        if age.total_seconds() < 0 or age > __import__("datetime").timedelta(days=predicate.max_age_days):
            return False
    return True


def evaluates_to_member(definition, facts, *, subject_type, effective_as_of):
    """Return one stable boolean; no ranking, time lookup, or persistence."""
    if definition.allowed_subject_types and subject_type not in definition.allowed_subject_types:
        return False
    return all(any(_matches(predicate, fact, effective_as_of) for fact in facts) for predicate in definition.signal_predicates)
