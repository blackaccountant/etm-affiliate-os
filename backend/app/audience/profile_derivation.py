"""Pure deterministic selection and summary helpers for audience profiles."""

from __future__ import annotations

from datetime import datetime

from app.audience.contracts import AudienceSignalType
from app.audience.normalization import aware_utc
from app.audience.profile_contracts import AudienceProfileSummaryFact


class AudienceProfileDerivationError(ValueError):
    """A deterministic permanent rejection from profile derivation."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def canonical_signal_key(signal) -> tuple[str, str, str, str, str]:
    return (
        signal.signal_type,
        signal.topic_slug,
        signal.intent_stage or "",
        aware_utc(signal.observed_at, "observed_at").isoformat(),
        signal.id,
    )


def _validate_lineage(signals) -> None:
    by_id = {signal.id: signal for signal in signals}
    if len(by_id) != len(signals):
        raise AudienceProfileDerivationError("MALFORMED_SIGNAL_LINEAGE", "duplicate signal identity")
    for signal in signals:
        predecessor_id = signal.supersedes_signal_id
        if predecessor_id is not None and predecessor_id not in by_id:
            raise AudienceProfileDerivationError("MALFORMED_SIGNAL_LINEAGE", "supersession crosses the requested subject")
    for signal in signals:
        seen: set[str] = set()
        current = signal
        while current.supersedes_signal_id is not None:
            if current.id in seen:
                raise AudienceProfileDerivationError("MALFORMED_SIGNAL_LINEAGE", "supersession cycle")
            seen.add(current.id)
            current = by_id[current.supersedes_signal_id]


def effective_signals(signals, *, effective_as_of: datetime):
    """Return canonical active leaves without resolving conflicting factual signals."""
    as_of = aware_utc(effective_as_of, "effective_as_of")
    signals = list(signals)
    _validate_lineage(signals)
    superseded_ids = {signal.supersedes_signal_id for signal in signals if signal.supersedes_signal_id is not None}
    leaves = [signal for signal in signals if signal.id not in superseded_ids]
    return tuple(sorted(
        (signal for signal in leaves if signal.expires_at is None or aware_utc(signal.expires_at, "expires_at") > as_of),
        key=canonical_signal_key,
    ))


def profile_summary(signals) -> dict:
    """Build a bounded, canonical, signal-fact-only profile summary."""
    categories: dict[str, list[dict]] = {}
    for signal in sorted(signals, key=canonical_signal_key):
        fact = AudienceProfileSummaryFact(
            signal_id=signal.id,
            signal_type=signal.signal_type,
            topic=signal.topic_slug,
            topic_label=signal.topic_label,
            intent_stage=signal.intent_stage,
            strength=signal.strength,
            confidence=signal.confidence,
            observed_at=signal.observed_at,
            expires_at=signal.expires_at,
        ).to_dict()
        categories.setdefault(signal.signal_type, []).append(fact)
    return {"categories": {kind.value: categories[kind.value] for kind in AudienceSignalType if kind.value in categories}}
