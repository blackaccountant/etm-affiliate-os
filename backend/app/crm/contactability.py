"""Pure M8D point and Lead contactability decisions."""

from app.crm.contactability_contracts import (
    ContactabilityContext,
    ContactabilityReason,
    ContactabilityState,
    ContactPointSnapshot,
    LeadContactabilityResult,
    PointContactabilityResult,
    ResolvedContactPointState,
    ResolvedPermission,
    ResolvedSuppression,
)
from app.crm.contracts import ContactPointState, ContactPointVerificationState, EffectivePermissionState


_COMPATIBLE_CHANNELS = {
    "EMAIL": frozenset({"EMAIL"}),
    "PHONE": frozenset({"SMS", "WHATSAPP"}),
    "TELEGRAM": frozenset({"TELEGRAM"}),
    "WEBSITE": frozenset(),
    "SOCIAL_PROFILE": frozenset(),
}
_INFORMATIONAL = frozenset({"WEBSITE", "SOCIAL_PROFILE"})


def is_channel_compatible(kind: str, channel: str) -> bool:
    return channel in _COMPATIBLE_CHANNELS[kind]


def evaluate_contact_point(
    *,
    subject_type: str | None,
    contact_point: ContactPointSnapshot,
    context: ContactabilityContext,
    contact_state: ResolvedContactPointState,
    permission: ResolvedPermission,
    suppression: ResolvedSuppression,
) -> PointContactabilityResult:
    compatible = is_channel_compatible(contact_point.kind, context.channel)
    if subject_type is None:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.SUBJECT_UNAVAILABLE.value,)
    elif subject_type == "ANONYMOUS":
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.ANONYMOUS_SUBJECT.value,)
    elif contact_point.kind in _INFORMATIONAL:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.INFORMATIONAL_CONTACT_KIND.value,)
    elif not compatible:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.CHANNEL_INCOMPATIBLE.value,)
    elif contact_state.effective_state == ContactPointState.INVALID.value:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.CONTACT_POINT_INVALID.value,)
    elif contact_state.effective_state == ContactPointState.RETIRED.value:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.CONTACT_POINT_RETIRED.value,)
    elif suppression.is_suppressed:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, suppression.active_reason_codes
    elif permission.effective_permission == EffectivePermissionState.OPTED_OUT.value:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.PERMISSION_OPTED_OUT.value,)
    elif permission.effective_permission == EffectivePermissionState.REVOKED.value:
        state, reasons = ContactabilityState.NOT_CONTACTABLE.value, (ContactabilityReason.PERMISSION_REVOKED.value,)
    elif contact_state.effective_state is None:
        state, reasons = ContactabilityState.UNKNOWN.value, (ContactabilityReason.CONTACT_POINT_STATE_UNKNOWN.value,)
    elif contact_state.effective_verification != ContactPointVerificationState.VERIFIED.value:
        state, reasons = ContactabilityState.UNKNOWN.value, (ContactabilityReason.CONTACT_POINT_UNVERIFIED.value,)
    elif permission.effective_permission != EffectivePermissionState.CONSENTED.value:
        state, reasons = ContactabilityState.UNKNOWN.value, (ContactabilityReason.PERMISSION_UNKNOWN.value,)
    else:
        state, reasons = ContactabilityState.CONTACTABLE.value, (ContactabilityReason.CONTACTABLE_WITH_CONSENT.value,)
    return PointContactabilityResult(
        state=state,
        lead_id=contact_point.lead_id,
        contact_point_id=contact_point.id,
        channel=context.channel,
        purpose_key=context.purpose_key,
        evaluated_as_of=context.evaluated_as_of,
        effective_contact_state=contact_state.effective_state,
        effective_verification=contact_state.effective_verification,
        effective_permission=permission.effective_permission,
        suppression=suppression,
        reason_codes=reasons,
        winning_state_event_id=contact_state.winning_event_id,
        winning_permission_event_id=permission.winning_event_id,
        jurisdiction_context=permission.jurisdiction_context,
        channel_compatible=compatible,
    )


def aggregate_lead_contactability(
    lead_id: str,
    context: ContactabilityContext,
    point_results: tuple[PointContactabilityResult, ...],
) -> LeadContactabilityResult:
    ordered = tuple(sorted(point_results, key=lambda item: item.contact_point_id))
    compatible = tuple(item for item in ordered if item.channel_compatible)
    contactable = tuple(item.contact_point_id for item in compatible if item.state == ContactabilityState.CONTACTABLE.value)
    unknown = tuple(item.contact_point_id for item in compatible if item.state == ContactabilityState.UNKNOWN.value)
    if not compatible:
        state = ContactabilityState.NOT_CONTACTABLE.value
        reasons = (ContactabilityReason.NO_COMPATIBLE_CONTACT_POINT.value,)
    elif contactable:
        state = ContactabilityState.CONTACTABLE.value
        reasons = (ContactabilityReason.CONTACTABLE_WITH_CONSENT.value,)
    elif unknown:
        state = ContactabilityState.UNKNOWN.value
        reasons = tuple(sorted({reason for item in compatible for reason in item.reason_codes}))
    else:
        state = ContactabilityState.NOT_CONTACTABLE.value
        reasons = tuple(sorted({reason for item in compatible for reason in item.reason_codes}))
    return LeadContactabilityResult(
        state=state,
        lead_id=lead_id,
        channel=context.channel,
        purpose_key=context.purpose_key,
        evaluated_as_of=context.evaluated_as_of,
        reason_codes=reasons,
        point_results=ordered,
        contactable_point_ids=contactable,
        unknown_point_ids=unknown,
    )
