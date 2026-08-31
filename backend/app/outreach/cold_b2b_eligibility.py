"""Pure deterministic cold policy; frequency counts eligible authorizations, not deliveries."""

from app.outreach.cold_b2b_contracts import COLD_B2B_ELIGIBILITY_POLICY_VERSION, COLD_B2B_FREQUENCY_POLICY_VERSION, ColdAuthorizationState, ColdRequestedAction, ProspectingEligibilityAssessment, SUPPORTED_COLD_B2B_POLICY_PROFILES
from app.outreach.contracts import sha256_fingerprint

_APPROVED_PROVENANCE = frozenset({"PUBLIC_BUSINESS_SOURCE", "WEBSITE"})


def evaluate_cold_b2b_eligibility(*, subject_type, contact_kind, contact_state, verification_state, permission_state, suppression, provenance, organization_evidence_valid, policy_selection_valid, policy_profile_key, policy_profile_version, requested_action, prior_eligible, evaluated_at):
    reasons = []
    profile = SUPPORTED_COLD_B2B_POLICY_PROFILES.get(policy_profile_key)
    if not policy_selection_valid or profile is None or profile.version != policy_profile_version:
        state = ColdAuthorizationState.POLICY_UNAVAILABLE.value
        reasons.append("POLICY_UNAVAILABLE")
    else:
        state = ColdAuthorizationState.ELIGIBLE.value
        if subject_type != "ORGANIZATION": reasons.append("ORGANIZATION_REQUIRED")
        if not organization_evidence_valid: reasons.append("ORGANIZATION_EVIDENCE_UNAVAILABLE")
        if contact_kind != "EMAIL": reasons.append("EMAIL_REQUIRED")
        if contact_state != "ACTIVE": reasons.append("CONTACT_POINT_NOT_ACTIVE")
        if verification_state != "VERIFIED": reasons.append("CONTACT_POINT_NOT_VERIFIED")
        if not provenance: reasons.append("PROVENANCE_REQUIRED")
        elif not any(item.source_type in _APPROVED_PROVENANCE for item in provenance): reasons.append("PROVENANCE_NOT_APPROVED")
        if permission_state == "OPTED_OUT": reasons.append("PERMISSION_OPTED_OUT")
        if permission_state == "REVOKED": reasons.append("PERMISSION_REVOKED")
        if suppression.is_suppressed: reasons.extend(suppression.active_reason_codes)
        if requested_action == ColdRequestedAction.INITIAL.value and prior_eligible: reasons.append("INITIAL_ALREADY_AUTHORIZED")
        if requested_action == ColdRequestedAction.FOLLOW_UP.value:
            if not prior_eligible: reasons.append("FOLLOW_UP_REQUIRES_PRIOR_AUTHORIZATION")
            else:
                if evaluated_at - prior_eligible[0].evaluated_at < profile.minimum_follow_up_spacing: reasons.append("FOLLOW_UP_SPACING_NOT_MET")
                if sum(item.requested_action == ColdRequestedAction.FOLLOW_UP.value for item in prior_eligible) >= profile.maximum_follow_ups: reasons.append("FOLLOW_UP_LIMIT_REACHED")
        if reasons: state = ColdAuthorizationState.INELIGIBLE.value
    ordered = tuple(sorted(set(reasons or ["ELIGIBLE"])))
    decision_fingerprint = sha256_fingerprint({"contact_kind": contact_kind, "contact_state": contact_state, "frequency_policy_version": COLD_B2B_FREQUENCY_POLICY_VERSION, "organization_evidence_valid": organization_evidence_valid, "permission_state": permission_state, "policy_profile_key": policy_profile_key, "policy_profile_version": policy_profile_version, "policy_selection_valid": policy_selection_valid, "policy_version": COLD_B2B_ELIGIBILITY_POLICY_VERSION, "prior_authorization_ids": [item.id for item in prior_eligible], "provenance": sorted((item.id, item.provenance_fingerprint) for item in provenance), "reason_codes": ordered, "requested_action": requested_action, "state": state, "subject_type": subject_type, "suppression_event_ids": sorted(suppression.winning_event_ids), "verification_state": verification_state})
    return ProspectingEligibilityAssessment(state, ordered, COLD_B2B_ELIGIBILITY_POLICY_VERSION, COLD_B2B_FREQUENCY_POLICY_VERSION, policy_profile_key, policy_profile_version, decision_fingerprint)
