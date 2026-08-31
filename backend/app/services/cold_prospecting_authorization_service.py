"""PostgreSQL-serialized M9C2A authorization; it never creates delivery work."""

from sqlalchemy import text

from app.crm.contact_point_state_resolution import resolve_contact_point_state
from app.crm.permission_resolution import resolve_permission
from app.crm.suppression_resolution import resolve_suppression
from app.models.audience import AudienceSubject
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.models.crm import ContactPoint, ContactPointProvenance, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent
from app.outreach.cold_b2b_contracts import APPROVED_ORGANIZATION_EVIDENCE_SOURCES, CreateColdProspectingAuthorizationRequest, POLICY_SELECTION_SCHEMA_VERSION, SUPPORTED_COLD_B2B_POLICY_PROFILES
from app.outreach.cold_b2b_eligibility import evaluate_cold_b2b_eligibility
from app.outreach.contracts import OutreachError, sha256_fingerprint
from app.repositories.cold_prospecting_repository import ColdProspectingRepository


class ColdProspectingAuthorizationService:
    """Caller owns commit/rollback. Lock order is source identity, then frequency identity."""
    def __init__(self, db, *, allow_sqlite_for_tests=False):
        self.db, self.records, self.allow_sqlite_for_tests = db, ColdProspectingRepository(db), allow_sqlite_for_tests

    def _require_transaction_contract(self):
        dialect = self.db.bind.dialect.name
        if dialect == "sqlite" and self.allow_sqlite_for_tests: return
        if dialect != "postgresql": raise OutreachError("POSTGRES_REQUIRED", "cold authorization requires PostgreSQL")
        isolation = self.db.execute(text("SHOW transaction_isolation")).scalar_one().replace(" ", "_").upper()
        # Each statement after the transaction-scoped advisory locks must observe
        # commits made by the transaction that just released those locks.  A
        # REPEATABLE READ snapshot can be established by the isolation check (or
        # any caller query) before lock acquisition, and would then evaluate a
        # stale frequency/suppression history after waiting for the lock.
        if isolation != "READ_COMMITTED": raise OutreachError("ISOLATION_REQUIRED", "cold authorization requires READ COMMITTED for post-lock visibility")

    @staticmethod
    def _valid_organization(record, request):
        return bool(record and record.lead_id == request.lead_id and record.evidence_fingerprint == request.organization_evidence.expected_fingerprint and record.acceptance_state == "ACCEPTED" and record.source_classification in APPROVED_ORGANIZATION_EVIDENCE_SOURCES and record.source_record_fingerprint and record.evidence_schema_version)

    @staticmethod
    def _valid_policy(record, request):
        return bool(record and record.lead_id == request.lead_id and record.decision_fingerprint == request.policy_selection.expected_fingerprint and record.acceptance_state == "ACCEPTED" and record.selection_schema_version == POLICY_SELECTION_SCHEMA_VERSION and SUPPORTED_COLD_B2B_POLICY_PROFILES.get(record.profile_key) and SUPPORTED_COLD_B2B_POLICY_PROFILES[record.profile_key].version == record.profile_version)

    def create_or_reuse(self, request):
        if not isinstance(request, CreateColdProspectingAuthorizationRequest): raise OutreachError("INVALID_CONTRACT", "request must use the M9C2A contract")
        self._require_transaction_contract()
        self.records.acquire_lock("cold-source-v1", f"{request.source_namespace}\x00{request.source_event_key}")
        lead, point = self.db.get(Lead, request.lead_id), self.db.get(ContactPoint, request.contact_point_id)
        if lead is None or point is None or point.lead_id != request.lead_id: raise OutreachError("CONTACT_POINT_LEAD_MISMATCH", "contact point does not belong to Lead")
        organization = self.records.evidence(request.organization_evidence.organization_evidence_id)
        policy = self.records.policy_selection(request.policy_selection.policy_selection_id)
        provenance = tuple(self.db.query(ContactPointProvenance).filter_by(contact_point_id=point.id).all())
        if len(provenance) > 8: raise OutreachError("PROVENANCE_EVIDENCE_LIMIT", "cold authorization accepts at most eight provenance records")
        profile_key = policy.profile_key if policy else "policy-unavailable"
        profile_version = policy.profile_version if policy else "policy-unavailable"
        request_fingerprint = sha256_fingerprint({"request": request.request_fingerprint, "policy_profile_key": profile_key, "policy_profile_version": profile_version, "provenance": sorted((item.id, item.provenance_fingerprint) for item in provenance)})
        existing = self.records.authorization_by_source(request.source_namespace, request.source_event_key)
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint: raise OutreachError("IDEMPOTENCY_CONFLICT", "cold authorization conflicts")
            return existing, True
        self.records.acquire_lock("cold-frequency-v1", f"{lead.id}\x00{point.id}\x00EMAIL\x00{request.purpose_family}")
        profile = SUPPORTED_COLD_B2B_POLICY_PROFILES.get(profile_key)
        history = self.records.bounded_eligible_history(lead_id=lead.id, contact_point_id=point.id, purpose_family=request.purpose_family, limit=(profile.maximum_follow_ups + 1) if profile else 1)
        subject = self.db.get(AudienceSubject, lead.subject_id) if lead.subject_id else None
        state = resolve_contact_point_state(tuple(self.db.query(ContactPointStateEvent).filter_by(contact_point_id=point.id).all()), request.evaluated_at)
        permission = resolve_permission(tuple(self.db.query(PermissionEvent).filter_by(contact_point_id=point.id, channel="EMAIL", purpose_key=request.purpose_key).all()), contact_point_id=point.id, channel="EMAIL", purpose_key=request.purpose_key, evaluated_as_of=request.evaluated_at)
        suppression = resolve_suppression(tuple(self.db.query(SuppressionEvent).filter_by(lead_id=lead.id).all()), lead_id=lead.id, contact_point_id=point.id, channel="EMAIL", evaluated_as_of=request.evaluated_at)
        assessment = evaluate_cold_b2b_eligibility(subject_type=subject.subject_type if subject else None, contact_kind=point.kind, contact_state=state.effective_state, verification_state=state.effective_verification, permission_state=permission.effective_permission, suppression=suppression, provenance=provenance, organization_evidence_valid=self._valid_organization(organization, request), policy_selection_valid=self._valid_policy(policy, request), policy_profile_key=profile_key, policy_profile_version=profile_version, requested_action=request.requested_action, prior_eligible=history, evaluated_at=request.evaluated_at)
        evidence = {"organization_evidence_fingerprint": request.organization_evidence.expected_fingerprint, "policy_selection_fingerprint": request.policy_selection.expected_fingerprint, "provenance_ids": sorted(item.id for item in provenance), "provenance_fingerprints": sorted(item.provenance_fingerprint for item in provenance), "winning_permission_event_id": permission.winning_event_id, "winning_state_event_id": state.winning_event_id, "winning_suppression_event_ids": sorted(suppression.winning_event_ids)}
        return self.records.create_authorization_or_reuse(ColdProspectingAuthorization(lead_id=lead.id, contact_point_id=point.id, organization_evidence_id=organization.id if organization else None, policy_selection_id=policy.id if policy else None, channel="EMAIL", purpose_key=request.purpose_key, purpose_family=request.purpose_family, requested_action=request.requested_action, source_namespace=request.source_namespace, source_event_key=request.source_event_key, request_fingerprint=request_fingerprint, authorization_state=assessment.state, reason_codes=list(assessment.reason_codes), eligibility_policy_version=assessment.policy_version, frequency_policy_version=assessment.frequency_policy_version, policy_profile_key=assessment.policy_profile_key, decision_fingerprint=assessment.decision_fingerprint, evidence=evidence, evaluated_at=request.evaluated_at))
