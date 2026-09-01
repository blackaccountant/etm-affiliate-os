"""M9C2B4A local-only final authority boundary; it has no transport imports."""
from datetime import datetime, timezone
from hmac import compare_digest
from sqlalchemy import text, update, and_, exists
from app.crm.contact_point_state_resolution import resolve_contact_point_state
from app.crm.permission_resolution import resolve_permission
from app.crm.suppression_resolution import resolve_suppression
from app.models.audience import AudienceSubject
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdDispatchReservation, ColdT3Decision
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent
from app.models.execution import Execution
from app.outreach.cold_b2b_eligibility import evaluate_cold_b2b_eligibility
from app.outreach.cold_provider_approval_contracts import ColdProviderApprovalRegistry
from app.outreach.cold_recipient_resolution import ColdRecipientResolutionService
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.repositories.cold_dispatch_reservation_repository import ColdDispatchReservationRepository
from app.repositories.cold_prospecting_repository import advisory_lock_key, ColdProspectingRepository
from app.repositories.execution_repository import ExecutionRepository, ExecutionLeaseLostError
from app.services.cold_delivery_t3_service import ColdDeliveryT3Service

class ColdDeliveryPreSendService:
    def __init__(self, db, provider_registry=None):
        self.db = db; self.providers = provider_registry or ColdProviderApprovalRegistry(); self.records = ColdProspectingRepository(db); self.reservations = ColdDispatchReservationRepository(db)

    def _require_postgres(self):
        if self.db.bind.dialect.name != "postgresql": raise OutreachError("POSTGRES_REQUIRED", "cold pre-send requires PostgreSQL")
        if self.db.execute(text("SHOW transaction_isolation")).scalar_one().replace(" ", "_").upper() != "READ_COMMITTED": raise OutreachError("ISOLATION_REQUIRED", "cold pre-send requires READ COMMITTED")

    @staticmethod
    def fact_lock_key(lead_id, contact_point_id, purpose_key):
        return advisory_lock_key("cold-send-facts-v1", "\x00".join((lead_id, contact_point_id, "EMAIL", purpose_key)))

    def _lock_facts(self, operation):
        self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": self.fact_lock_key(operation.lead_id, operation.contact_point_id, operation.purpose_key)})

    def _block(self, operation, state, authority, reasons, now):
        # Only bounded codes are evidence; exception/provider text never reaches storage.
        reasons = sorted(set(reasons))[:16]
        expected_revision, event_sequence = state.revision, state.next_event_sequence
        event = ColdDeliveryEvent(operation_id=operation.id, sequence_number=event_sequence, event_type="PRE_SEND_BLOCKED", occurred_at=now, source_namespace="cold-b2b-b4a-v1", source_event_key=f"{operation.id}:{expected_revision}:{authority.execution_id}:{authority.lease_generation}:blocked", event_fingerprint=sha256_fingerprint({"operation": operation.id, "revision": expected_revision, "reasons": reasons}), safe_payload={"reason_codes": reasons})
        result = self.db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == operation.id, ColdDeliveryOperationState.current_state == "DISPATCH_PLANNED", ColdDeliveryOperationState.revision == expected_revision, ColdDeliveryOperationState.next_event_sequence == event_sequence, ColdDeliveryOperationState.active_execution_id == str(authority.execution_id), ColdDeliveryOperationState.active_fence_identity == f"{authority.lease_owner}:{authority.lease_generation}").values(current_state="PRE_SEND_BLOCKED", revision=expected_revision + 1, next_event_sequence=event_sequence + 1, updated_at=now))
        if result.rowcount != 1: raise OutreachError("STALE_AUTHORITY", "pre-send authority was superseded")
        self.db.add(event); self.db.flush(); self.db.commit()
        return {"operation_id": operation.id, "state": "PRE_SEND_BLOCKED", "reason_codes": reasons}

    def reserve(self, operation_id, authority):
        """Reserve exactly once or fail closed. This method never sends or calls a provider."""
        self._require_postgres()
        try:
            # A harmless first lookup supplies the deterministic fact lock identity; all authority facts are reread after it.
            candidate = self.db.get(ColdDeliveryOperation, operation_id)
            if candidate is None: raise OutreachError("OPERATION_UNAVAILABLE", "cold operation is unavailable")
            self._lock_facts(candidate)
            execution = ExecutionRepository(self.db).verify_active_authority(authority)
            state = self.db.query(ColdDeliveryOperationState).filter_by(operation_id=operation_id).with_for_update().one_or_none()
            operation = self.db.query(ColdDeliveryOperation).filter_by(id=operation_id).with_for_update().one_or_none()
            if state is None or operation is None: raise OutreachError("OPERATION_UNAVAILABLE", "cold operation is unavailable")
            existing = self.reservations.by_operation(operation.id)
            if existing is not None and state.current_state == "DISPATCHING": self.db.commit(); return {"operation_id": operation.id, "state": "DISPATCHING", "reservation_id": existing.reservation_id, "reused": True}
            if state.current_state != "DISPATCH_PLANNED": raise OutreachError("PRE_SEND_STATE_UNAVAILABLE", "cold operation is not dispatch planned")
            expected_revision, event_sequence = state.revision, state.next_event_sequence
            fence = f"{authority.lease_owner}:{authority.lease_generation}"
            if state.active_execution_id != str(authority.execution_id) or state.active_fence_identity != fence: raise OutreachError("STALE_AUTHORITY", "cold delivery execution authority was superseded")
            lead = self.db.query(Lead).filter_by(id=operation.lead_id).with_for_update().one_or_none()
            point = self.db.query(ContactPoint).filter_by(id=operation.contact_point_id).with_for_update().one_or_none()
            auth = self.db.query(ColdProspectingAuthorization).filter_by(id=operation.cold_authorization_id).with_for_update().one_or_none()
            decisions = self.db.query(ColdT3Decision).filter_by(operation_id=operation.id, decision="ALLOWED").order_by(ColdT3Decision.recorded_at.desc()).all()
            # Current facts must be evaluated only after every blocking lock.
            # READ COMMITTED then observes invalidations committed while waiting.
            facts_as_of = datetime.now(timezone.utc)
            reasons=[]
            try: valid, org, policy, provenance = ColdDeliveryT3Service(self.db)._binding(operation, auth) if auth else (False, None, None, [])
            except Exception: valid, org, policy, provenance = False, None, None, []
            if not valid or not auth or auth.authorization_state != "ELIGIBLE" or not lead or not point or point.lead_id != operation.lead_id: reasons.append("AUTHORIZATION_UNAVAILABLE")
            subject = self.db.get(AudienceSubject, lead.subject_id) if lead and lead.subject_id else None
            state_fact = resolve_contact_point_state(tuple(self.db.query(ContactPointStateEvent).filter_by(contact_point_id=operation.contact_point_id).all()), facts_as_of)
            permission = resolve_permission(tuple(self.db.query(PermissionEvent).filter_by(contact_point_id=operation.contact_point_id, channel="EMAIL", purpose_key=operation.purpose_key).all()), contact_point_id=operation.contact_point_id, channel="EMAIL", purpose_key=operation.purpose_key, evaluated_as_of=facts_as_of)
            suppression = resolve_suppression(tuple(self.db.query(SuppressionEvent).filter_by(lead_id=operation.lead_id).all()), lead_id=operation.lead_id, contact_point_id=operation.contact_point_id, channel="EMAIL", evaluated_as_of=facts_as_of)
            assessment = evaluate_cold_b2b_eligibility(subject_type=subject.subject_type if subject else None, contact_kind=point.kind if point else None, contact_state=state_fact.effective_state, verification_state=state_fact.effective_verification, permission_state=permission.effective_permission, suppression=suppression, provenance=tuple(provenance), organization_evidence_valid=bool(org and org.lead_id == operation.lead_id and org.acceptance_state == "ACCEPTED"), policy_selection_valid=bool(policy and policy.lead_id == operation.lead_id and policy.acceptance_state == "ACCEPTED"), policy_profile_key=policy.profile_key if policy else "unavailable", policy_profile_version=policy.profile_version if policy else "unavailable", requested_action=operation.action, prior_eligible=[auth] if auth and operation.action == "FOLLOW_UP" else [], evaluated_at=facts_as_of)
            reasons.extend(x for x in assessment.reason_codes if x not in {"ELIGIBLE", "INITIAL_ALREADY_AUTHORIZED", "FOLLOW_UP_REQUIRES_PRIOR_AUTHORIZATION", "FOLLOW_UP_SPACING_NOT_MET", "FOLLOW_UP_LIMIT_REACHED"})
            if len(decisions) != 1: reasons.append("T3_AUTHORITY_UNAVAILABLE")
            recipient_fp = None
            if not reasons:
                try: recipient_fp = ColdRecipientResolutionService.resolve_email(locked_contact_point=point, lead_id=operation.lead_id, contact_point_id=operation.contact_point_id).fingerprint()
                except Exception: reasons.append("RECIPIENT_RESOLUTION_FAILED")
            if recipient_fp and not compare_digest(recipient_fp, decisions[0].recipient_fingerprint): reasons.append("RECIPIENT_FINGERPRINT_CHANGED")
            try: approval = self.providers.select() if not reasons else None
            except Exception: reasons.append("COLD_PROVIDER_NOT_APPROVED"); approval = None
            if reasons: return self._block(operation, state, authority, reasons, facts_as_of)
            write_now = datetime.now(timezone.utc)
            idem = sha256_fingerprint({"schema": "cold-dispatch-v1", "operation_id": operation.id, "provider_key": approval.provider_key, "provider_contract_version": approval.provider_contract_version})
            reservation = ColdDispatchReservation(operation_id=operation.id, provider_key=approval.provider_key, provider_contract_version=approval.provider_contract_version, idempotency_key=idem, execution_id=str(authority.execution_id), execution_fence_identity=fence, expected_state_revision=expected_revision, recipient_fingerprint=recipient_fp, content_fingerprint=operation.message_content_fingerprint, sender_fingerprint=sha256_fingerprint({"provider": approval.provider_key, "sender": "cold-approved"}), provider_payload_fingerprint=sha256_fingerprint({"operation": operation.id, "content": operation.message_content_fingerprint, "recipient": recipient_fp, "provider": approval.provider_key}))
            self.db.add(reservation); self.db.flush()
            live_execution = exists().where(and_(Execution.id == authority.execution_id, Execution.status.in_(("RUNNING", "RETRYING")), Execution.lease_owner == authority.lease_owner, Execution.lease_generation == authority.lease_generation, Execution.lease_expires_at > write_now))
            updated = self.db.execute(update(ColdDeliveryOperationState).where(ColdDeliveryOperationState.operation_id == operation.id, ColdDeliveryOperationState.current_state == "DISPATCH_PLANNED", ColdDeliveryOperationState.revision == expected_revision, ColdDeliveryOperationState.next_event_sequence == event_sequence, ColdDeliveryOperationState.active_execution_id == str(authority.execution_id), ColdDeliveryOperationState.active_fence_identity == fence, live_execution).values(current_state="DISPATCHING", revision=expected_revision+1, next_event_sequence=event_sequence+1, updated_at=write_now))
            if updated.rowcount != 1: raise OutreachError("STALE_AUTHORITY", "pre-send authority was superseded")
            self.db.add(ColdDeliveryEvent(operation_id=operation.id, sequence_number=event_sequence, event_type="DISPATCH_RESERVED", occurred_at=write_now, source_namespace="cold-b2b-b4a-v1", source_event_key=f"{operation.id}:{expected_revision}:{authority.execution_id}:{authority.lease_generation}:reserved", event_fingerprint=sha256_fingerprint({"operation": operation.id, "reservation": reservation.reservation_id}), safe_payload={"reservation_id": reservation.reservation_id, "provider_key": approval.provider_key, "idempotency_key": idem}))
            self.db.flush(); self.db.commit(); return {"operation_id": operation.id, "state": "DISPATCHING", "reservation_id": reservation.reservation_id, "reused": False}
        except (OutreachError, ExecutionLeaseLostError): self.db.rollback(); raise
        except Exception: self.db.rollback(); raise
