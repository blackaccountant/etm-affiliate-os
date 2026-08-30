"""Pure deterministic transition policy for the M8C Lead lifecycle."""

from __future__ import annotations

from app.crm.lifecycle_contracts import (
    LeadLifecycleState,
    LifecycleError,
    LifecycleTransitionDecision,
)


_ALLOWED = {
    None: frozenset({LeadLifecycleState.DISCOVERED.value}),
    LeadLifecycleState.DISCOVERED.value: frozenset({
        LeadLifecycleState.ENRICHED.value,
        LeadLifecycleState.ARCHIVED.value,
    }),
    LeadLifecycleState.ENRICHED.value: frozenset({
        LeadLifecycleState.QUALIFIED.value,
        LeadLifecycleState.ARCHIVED.value,
    }),
    LeadLifecycleState.QUALIFIED.value: frozenset({
        LeadLifecycleState.READY_FOR_REVIEW.value,
        LeadLifecycleState.ARCHIVED.value,
    }),
    LeadLifecycleState.READY_FOR_REVIEW.value: frozenset({LeadLifecycleState.ARCHIVED.value}),
    LeadLifecycleState.ARCHIVED.value: frozenset(),
}


def validate_lifecycle_transition(
    current_state: str | None,
    requested_state: str,
    *,
    has_qualifying_assessment: bool = False,
) -> LifecycleTransitionDecision:
    """Validate only explicit v1 transitions; no state or qualification inference."""
    try:
        current = None if current_state is None else LeadLifecycleState(current_state).value
        requested = LeadLifecycleState(requested_state).value
    except (TypeError, ValueError) as exc:
        raise LifecycleError("INVALID_LIFECYCLE_STATE", "lifecycle state is unsupported") from exc
    if requested not in _ALLOWED[current]:
        raise LifecycleError("INVALID_LIFECYCLE_TRANSITION", "lifecycle transition is not allowed")
    if requested == LeadLifecycleState.QUALIFIED.value and not has_qualifying_assessment:
        raise LifecycleError(
            "QUALIFYING_ASSESSMENT_REQUIRED",
            "QUALIFIED lifecycle requires a linked qualifying assessment",
        )
    return LifecycleTransitionDecision(current, requested)
