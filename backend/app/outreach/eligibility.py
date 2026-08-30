"""Pure deterministic outreach-eligibility-v1 policy."""

from app.crm.contactability_contracts import ContactabilityState, PointContactabilityResult
from app.outreach.contracts import (
    OUTREACH_ELIGIBILITY_POLICY_VERSION,
    OutreachEligibilityFacts,
    OutreachEligibilityReason,
    OutreachEligibilityResult,
    OutreachEligibilityState,
    sha256_fingerprint,
)


def evaluate_outreach_eligibility(facts: OutreachEligibilityFacts) -> OutreachEligibilityResult:
    result = facts.contactability_result
    reasons: list[str] = []
    state = OutreachEligibilityState.ELIGIBLE.value

    if not isinstance(result, PointContactabilityResult):
        state = OutreachEligibilityState.POLICY_UNAVAILABLE.value
        reasons.append(OutreachEligibilityReason.CONTACTABILITY_UNAVAILABLE.value)
    else:
        if result.lead_id != facts.lead_id:
            reasons.append(OutreachEligibilityReason.LEAD_MISMATCH.value)
        if result.contact_point_id != facts.contact_point_id:
            reasons.append(OutreachEligibilityReason.CONTACT_POINT_MISMATCH.value)
        if result.channel != facts.channel:
            reasons.append(OutreachEligibilityReason.CHANNEL_MISMATCH.value)
        if result.purpose_key != facts.purpose_key:
            reasons.append(OutreachEligibilityReason.PURPOSE_MISMATCH.value)
        if result.state == ContactabilityState.UNKNOWN.value:
            reasons.append(OutreachEligibilityReason.CONTACTABILITY_UNKNOWN.value)
        elif result.state != ContactabilityState.CONTACTABLE.value:
            reasons.append(OutreachEligibilityReason.CONTACT_NOT_CONTACTABLE.value)
        if reasons:
            state = OutreachEligibilityState.INELIGIBLE.value

    if not facts.message_contract_valid:
        reasons.append(OutreachEligibilityReason.MESSAGE_CONTRACT_INVALID.value)
        if state != OutreachEligibilityState.POLICY_UNAVAILABLE.value:
            state = OutreachEligibilityState.INELIGIBLE.value
    if not reasons:
        reasons.append(OutreachEligibilityReason.ELIGIBLE.value)

    ordered_reasons = tuple(sorted(set(reasons)))
    evaluated_as_of = result.evaluated_as_of if isinstance(result, PointContactabilityResult) else None
    contactability_state = result.state if isinstance(result, PointContactabilityResult) else None
    fingerprint = sha256_fingerprint({
        "channel": facts.channel,
        "contact_point_id": facts.contact_point_id,
        "contactability": _contactability_material(result),
        "lead_id": facts.lead_id,
        "message_contract_valid": facts.message_contract_valid,
        "policy_version": OUTREACH_ELIGIBILITY_POLICY_VERSION,
        "purpose_key": facts.purpose_key,
        "reason_codes": ordered_reasons,
        "state": state,
    })
    return OutreachEligibilityResult(
        state, ordered_reasons, OUTREACH_ELIGIBILITY_POLICY_VERSION,
        fingerprint, evaluated_as_of, contactability_state,
    )


def _contactability_material(result: object) -> object:
    if not isinstance(result, PointContactabilityResult):
        return None
    return {
        "channel": result.channel,
        "contact_point_id": result.contact_point_id,
        "evaluated_as_of": result.evaluated_as_of.isoformat(),
        "lead_id": result.lead_id,
        "purpose_key": result.purpose_key,
        "reason_codes": sorted(set(result.reason_codes)),
        "state": result.state,
        "winning_permission_event_id": result.winning_permission_event_id,
        "winning_state_event_id": result.winning_state_event_id,
        "winning_suppression_event_ids": sorted(set(result.suppression.winning_event_ids)),
    }
