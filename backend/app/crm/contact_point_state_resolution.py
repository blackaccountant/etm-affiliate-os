"""Pure explicit-as-of resolution of frozen contact-point state history."""

from app.crm.contactability_contracts import (
    ContactPointStateEventSnapshot,
    ResolvedContactPointState,
)
from app.crm.contracts import ContactPointState, ContactPointVerificationState, aware_utc


_STATE_TIE_RANK = {
    ContactPointState.ACTIVE.value: 0,
    ContactPointState.RETIRED.value: 1,
    ContactPointState.INVALID.value: 2,
}
_VERIFICATION_TIE_RANK = {
    ContactPointVerificationState.VERIFIED.value: 0,
    ContactPointVerificationState.UNVERIFIED.value: 1,
}


def resolve_contact_point_state(
    events: tuple[ContactPointStateEventSnapshot, ...],
    evaluated_as_of,
) -> ResolvedContactPointState:
    as_of = aware_utc(evaluated_as_of, "evaluated_as_of")
    eligible = [
        event for event in events
        if event.occurred_at <= as_of and event.recorded_at <= as_of
    ]
    if not eligible:
        return ResolvedContactPointState(None, None, None)
    winner = max(
        eligible,
        key=lambda event: (
            event.occurred_at,
            event.recorded_at,
            _STATE_TIE_RANK[event.state],
            _VERIFICATION_TIE_RANK[event.verification_state],
            event.id,
        ),
    )
    return ResolvedContactPointState(winner.state, winner.verification_state, winner.id)
