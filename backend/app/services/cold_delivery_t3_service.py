"""Fenced, provider-free fresh T3 evaluation for a cold delivery operation."""
from datetime import datetime, timezone
from hmac import compare_digest
from sqlalchemy import text, update
from app.crm.contact_point_state_resolution import resolve_contact_point_state
from app.crm.permission_resolution import resolve_permission
from app.crm.suppression_resolution import resolve_suppression
from app.models.audience import AudienceSubject
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdT3Decision
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent
from app.outreach.cold_b2b_contracts import CreateColdProspectingAuthorizationRequest, OrganizationEvidenceAuthorityReference, PolicySelectionAuthorityReference, SUPPORTED_COLD_B2B_POLICY_PROFILES
from app.outreach.cold_b2b_eligibility import evaluate_cold_b2b_eligibility
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.outreach.cold_recipient_resolution import ColdRecipientResolutionService
from app.repositories.cold_prospecting_repository import ColdProspectingRepository
from app.repositories.execution_repository import ExecutionRepository


class ColdDeliveryT3Service:
    def __init__(self, db): self.db, self.records = db, ColdProspectingRepository(db)

    def _require_transaction_contract(self):
        """T3 must observe facts committed while it was waiting on its locks."""
        if self.db.bind.dialect.name != "postgresql":
            raise OutreachError("POSTGRES_REQUIRED", "cold T3 requires PostgreSQL")
        isolation = self.db.execute(text("SHOW transaction_isolation")).scalar_one().replace(" ", "_").upper()
        if isolation != "READ_COMMITTED":
            raise OutreachError("ISOLATION_REQUIRED", "cold T3 requires READ COMMITTED for post-lock visibility")

    def _binding(self, operation, auth):
        if (
            operation.lead_id != auth.lead_id
            or operation.contact_point_id != auth.contact_point_id
            or operation.purpose_key != auth.purpose_key
            or operation.action != auth.requested_action
        ):
            return False, None, None, []
        org, policy = self.records.evidence(auth.organization_evidence_id), self.records.policy_selection(auth.policy_selection_id)
        if policy is None or auth.policy_profile_key != policy.profile_key:
            return False, org, policy, []
        evidence = auth.evidence or {}
        prov_ids = tuple(evidence.get("provenance_ids", ()))
        provenance = self.db.query(ContactPointProvenance).filter(ContactPointProvenance.id.in_(prov_ids)).all() if prov_ids else []
        if len(provenance) != len(prov_ids): return False, org, policy, provenance
        committed_provenance_fingerprints = tuple(sorted(evidence.get("provenance_fingerprints", ())))
        actual_provenance_fingerprints = tuple(sorted(item.provenance_fingerprint for item in provenance))
        if committed_provenance_fingerprints != actual_provenance_fingerprints:
            return False, org, policy, provenance
        request = CreateColdProspectingAuthorizationRequest(auth.lead_id, auth.contact_point_id, auth.purpose_key, auth.requested_action, auth.source_namespace, auth.source_event_key, OrganizationEvidenceAuthorityReference(auth.organization_evidence_id, evidence.get("organization_evidence_fingerprint", "")), PolicySelectionAuthorityReference(auth.policy_selection_id, evidence.get("policy_selection_fingerprint", "")), operation.message_content_fingerprint, auth.evaluated_at)
        outer = sha256_fingerprint({"request": request.request_fingerprint, "policy_profile_key": policy.profile_key if policy else "policy-unavailable", "policy_profile_version": policy.profile_version if policy else "policy-unavailable", "provenance": sorted((item.id, item.provenance_fingerprint) for item in provenance)})
        return compare_digest(outer, auth.request_fingerprint), org, policy, provenance

    def evaluate_and_plan(self, operation_id, authority):
        self._require_transaction_contract()
        now = datetime.now(timezone.utc); execution = ExecutionRepository(self.db).verify_active_authority(authority)
        state = self.db.query(ColdDeliveryOperationState).filter_by(operation_id=operation_id).with_for_update().one_or_none()
        operation = self.db.get(ColdDeliveryOperation, operation_id)
        if state is None or operation is None or state.current_state != "READY": raise OutreachError("T3_STATE_UNAVAILABLE", "cold delivery operation is not READY")
        fence = f"{authority.lease_owner}:{authority.lease_generation}"
        expected_revision = state.revision
        event_sequence = state.next_event_sequence
        if state.active_execution_id != str(authority.execution_id) or state.active_fence_identity != fence: raise OutreachError("STALE_AUTHORITY", "cold delivery execution authority was superseded")
        lead = self.db.query(Lead).filter_by(id=operation.lead_id).with_for_update().one_or_none()
        point = self.db.query(ContactPoint).filter_by(id=operation.contact_point_id).with_for_update().one_or_none()
        auth = self.db.get(ColdProspectingAuthorization, operation.cold_authorization_id)
        reasons = []
        try:
            valid_binding, org, policy, provenance = self._binding(operation, auth) if auth else (False, None, None, [])
        except Exception:
            valid_binding, org, policy, provenance = False, None, None, []
        if not valid_binding: reasons.append("AUTHORIZED_CONTENT_MISMATCH")
        if not auth or auth.authorization_state != "ELIGIBLE" or not lead or not point or point.lead_id != operation.lead_id: reasons.append("AUTHORIZATION_UNAVAILABLE")
        profile = SUPPORTED_COLD_B2B_POLICY_PROFILES.get(policy.profile_key) if policy else None
        subject = self.db.get(AudienceSubject, lead.subject_id) if lead and lead.subject_id else None
        state_fact = resolve_contact_point_state(tuple(self.db.query(ContactPointStateEvent).filter_by(contact_point_id=operation.contact_point_id).all()), now)
        permission = resolve_permission(tuple(self.db.query(PermissionEvent).filter_by(contact_point_id=operation.contact_point_id, channel="EMAIL", purpose_key=operation.purpose_key).all()), contact_point_id=operation.contact_point_id, channel="EMAIL", purpose_key=operation.purpose_key, evaluated_as_of=now)
        suppression = resolve_suppression(tuple(self.db.query(SuppressionEvent).filter_by(lead_id=operation.lead_id).all()), lead_id=operation.lead_id, contact_point_id=operation.contact_point_id, channel="EMAIL", evaluated_as_of=now)
        assessment = evaluate_cold_b2b_eligibility(subject_type=subject.subject_type if subject else None, contact_kind=point.kind if point else None, contact_state=state_fact.effective_state, verification_state=state_fact.effective_verification, permission_state=permission.effective_permission, suppression=suppression, provenance=tuple(provenance), organization_evidence_valid=bool(org and org.lead_id == operation.lead_id and org.acceptance_state == "ACCEPTED"), policy_selection_valid=bool(policy and policy.lead_id == operation.lead_id and policy.acceptance_state == "ACCEPTED"), policy_profile_key=policy.profile_key if policy else "policy-unavailable", policy_profile_version=policy.profile_version if policy else "policy-unavailable", requested_action=operation.action, prior_eligible=[auth] if operation.action == "FOLLOW_UP" and auth else [], evaluated_at=now)
        reasons.extend(item for item in assessment.reason_codes if item not in {"INITIAL_ALREADY_AUTHORIZED", "FOLLOW_UP_REQUIRES_PRIOR_AUTHORIZATION", "FOLLOW_UP_SPACING_NOT_MET", "FOLLOW_UP_LIMIT_REACHED", "ELIGIBLE"})
        recipient_fp = None
        if not reasons:
            try:
                recipient_fp = ColdRecipientResolutionService.resolve_email(
                    locked_contact_point=point,
                    lead_id=operation.lead_id,
                    contact_point_id=operation.contact_point_id,
                ).fingerprint()
            except Exception: reasons.append("RECIPIENT_RESOLUTION_FAILED")
        decision = "BLOCKED" if reasons else "ALLOWED"; target = "T3_BLOCKED" if reasons else "DISPATCH_PLANNED"
        auth_fp = auth.request_fingerprint if valid_binding else sha256_fingerprint({"operation_id": operation.id, "binding": "mismatch"})
        authority_fp = sha256_fingerprint({"operation_id": operation.id, "authorization_id": operation.cold_authorization_id, "state_revision": expected_revision, "fence": fence, "content_fingerprint": operation.message_content_fingerprint})
        source_key = f"{operation.id}:{expected_revision}:{authority.execution_id}:{authority.lease_generation}"
        self.db.add(ColdT3Decision(operation_id=operation.id, cold_authorization_id=operation.cold_authorization_id, authorization_fingerprint=auth_fp, evaluated_at=now, policy_fingerprint=assessment.decision_fingerprint, authority_fingerprint=authority_fp, crm_evidence_ids=[x for x in (auth.organization_evidence_id if auth else None, auth.policy_selection_id if auth else None, state_fact.winning_event_id, permission.winning_event_id, *suppression.winning_event_ids) if x], recipient_fingerprint=recipient_fp, decision=decision, reason_codes=sorted(set(reasons or ["T3_ALLOWED"])), decision_schema_version="cold-t3-decision-v1", source_namespace="cold-b2b-t3-v1", source_event_key=source_key))
        updated = self.db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == operation.id, ColdDeliveryOperationState.revision == expected_revision, ColdDeliveryOperationState.next_event_sequence == event_sequence, ColdDeliveryOperationState.active_execution_id == str(authority.execution_id), ColdDeliveryOperationState.active_fence_identity == fence).values(current_state=target, revision=expected_revision + 1, next_event_sequence=event_sequence + 1, updated_at=now))
        if updated.rowcount != 1: self.db.rollback(); raise OutreachError("STALE_AUTHORITY", "cold delivery state was superseded")
        self.db.add(ColdDeliveryEvent(operation_id=operation.id, sequence_number=event_sequence, event_type=f"T3_{decision}", occurred_at=now, source_namespace="cold-b2b-t3-v1", source_event_key=source_key, event_fingerprint=sha256_fingerprint({"operation_id": operation.id, "decision": decision, "revision": expected_revision, "authority": authority_fp}), safe_payload={"decision": decision, "reason_codes": sorted(set(reasons or ["T3_ALLOWED"]))}))
        self.db.flush(); self.db.commit(); return {"operation_id": operation.id, "decision": decision, "state": target}
