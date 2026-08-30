"""Pure independent-scope resolution of frozen suppression history."""

from app.crm.contactability_contracts import (
    ContactabilityReason,
    ResolvedSuppression,
    SuppressionEventSnapshot,
    SuppressionScopeResolution,
)
from app.crm.contracts import SuppressionAction, SuppressionScope, aware_utc


_ACTION_TIE_RANK = {
    SuppressionAction.LIFTED.value: 0,
    SuppressionAction.APPLIED.value: 1,
}
_SCOPE_REASON = {
    SuppressionScope.GLOBAL_LEAD.value: ContactabilityReason.SUPPRESSED_GLOBAL.value,
    SuppressionScope.LEAD_CHANNEL.value: ContactabilityReason.SUPPRESSED_CHANNEL.value,
    SuppressionScope.CONTACT_POINT_CHANNEL.value: ContactabilityReason.SUPPRESSED_CONTACT_POINT.value,
}


def _matches_scope(event, scope, lead_id, contact_point_id, channel):
    if event.lead_id != lead_id or event.scope != scope:
        return False
    if scope == SuppressionScope.GLOBAL_LEAD.value:
        return event.contact_point_id is None and event.channel is None
    if scope == SuppressionScope.LEAD_CHANNEL.value:
        return event.contact_point_id is None and event.channel == channel
    return event.contact_point_id == contact_point_id and event.channel == channel


def resolve_suppression(
    events: tuple[SuppressionEventSnapshot, ...],
    *,
    lead_id: str,
    contact_point_id: str,
    channel: str,
    evaluated_as_of,
) -> ResolvedSuppression:
    as_of = aware_utc(evaluated_as_of, "evaluated_as_of")
    resolutions = []
    for scope in (
        SuppressionScope.GLOBAL_LEAD.value,
        SuppressionScope.LEAD_CHANNEL.value,
        SuppressionScope.CONTACT_POINT_CHANNEL.value,
    ):
        eligible = [
            event for event in events
            if _matches_scope(event, scope, lead_id, contact_point_id, channel)
            and event.effective_at <= as_of
            and event.recorded_at <= as_of
        ]
        winner = max(
            eligible,
            key=lambda event: (
                event.effective_at,
                event.recorded_at,
                _ACTION_TIE_RANK[event.action],
                event.id,
            ),
            default=None,
        )
        resolutions.append(SuppressionScopeResolution(
            scope=scope,
            is_applied=winner is not None and winner.action == SuppressionAction.APPLIED.value,
            winning_event_id=winner.id if winner else None,
            reason=winner.reason if winner else None,
        ))
    active = tuple(item for item in resolutions if item.is_applied)
    return ResolvedSuppression(
        is_suppressed=bool(active),
        scopes=tuple(resolutions),
        active_reason_codes=tuple(_SCOPE_REASON[item.scope] for item in active),
        winning_event_ids=tuple(item.winning_event_id for item in resolutions if item.winning_event_id),
    )
