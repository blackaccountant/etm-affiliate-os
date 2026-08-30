"""Shared deterministic safety checks for audience-derived topics."""

from app.audience.normalization import required_text

_PROHIBITED_TOPIC_TERMS = (
    "religion", "race", "ethnicity", "political", "health", "sexual-orientation",
)


class AudienceSafetyError(ValueError):
    category = "SENSITIVE_SIGNAL_BLOCKED"


def validate_audience_topic(topic: object) -> str:
    """Reject the frozen prohibited-topic set without consulting external state."""
    value = required_text(topic, "topic", lowercase=True)
    if any(term in value for term in _PROHIBITED_TOPIC_TERMS):
        raise AudienceSafetyError("sensitive targeting signal blocked")
    return value
