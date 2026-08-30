"""Pure exact-scope resolution of frozen permission history."""

from app.crm.contactability_contracts import PermissionEventSnapshot, ResolvedPermission
from app.crm.contracts import EffectivePermissionState, PermissionEventType, aware_utc


_TIE_RANK = {
    PermissionEventType.CONSENTED.value: 0,
    PermissionEventType.UNKNOWN.value: 1,
    PermissionEventType.OPTED_OUT.value: 2,
    PermissionEventType.REVOKED.value: 3,
}


def resolve_permission(
    events: tuple[PermissionEventSnapshot, ...],
    *,
    contact_point_id: str,
    channel: str,
    purpose_key: str,
    evaluated_as_of,
) -> ResolvedPermission:
    as_of = aware_utc(evaluated_as_of, "evaluated_as_of")
    eligible = [
        event for event in events
        if event.contact_point_id == contact_point_id
        and event.channel == channel
        and event.purpose_key == purpose_key
        and event.occurred_at <= as_of
        and event.recorded_at <= as_of
    ]
    if not eligible:
        return ResolvedPermission(EffectivePermissionState.UNKNOWN.value, None, None)
    winner = max(
        eligible,
        key=lambda event: (
            event.occurred_at,
            event.recorded_at,
            _TIE_RANK[event.event_type],
            event.id,
        ),
    )
    return ResolvedPermission(winner.event_type, winner.id, winner.jurisdiction_context)
