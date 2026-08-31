"""Trusted ingestion boundary for immutable M9C2A organization and policy authorities."""

from datetime import datetime

from app.models.cold_prospecting import ColdProspectingOrganizationEvidence, ColdProspectingPolicySelection
from app.outreach.cold_b2b_contracts import APPROVED_ORGANIZATION_EVIDENCE_SOURCES, ORGANIZATION_EVIDENCE_SCHEMA_VERSION, POLICY_SELECTION_SCHEMA_VERSION, SUPPORTED_COLD_B2B_POLICY_PROFILES, opaque_source_namespace
from app.outreach.contracts import OutreachError, aware_utc, fingerprint, required_text, sha256_fingerprint


class ColdProspectingAuthorityRegistrationService:
    """Separate from authorization; callers supply only opaque SHA-256 source identities."""
    def __init__(self, db): self.db = db

    def register_organization_evidence(self, *, lead_id, source_namespace, source_event_key, source_classification, source_record_fingerprint, evidence_fingerprint, evaluated_at: datetime):
        if source_classification not in APPROVED_ORGANIZATION_EVIDENCE_SOURCES: raise OutreachError("UNSUPPORTED_ORGANIZATION_EVIDENCE", "organization source is not approved")
        lead_id = required_text(lead_id, "lead_id", 36); source_namespace = opaque_source_namespace(source_namespace); source_event_key = fingerprint(source_event_key, "source_event_key")
        source_record_fingerprint = fingerprint(source_record_fingerprint, "source_record_fingerprint"); evidence_fingerprint = fingerprint(evidence_fingerprint, "evidence_fingerprint")
        existing = self.db.query(ColdProspectingOrganizationEvidence).filter_by(source_namespace=source_namespace, source_event_key=source_event_key).one_or_none()
        request_fingerprint = sha256_fingerprint({"lead_id": lead_id, "source_classification": source_classification, "source_record_fingerprint": source_record_fingerprint, "evidence_fingerprint": evidence_fingerprint})
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint: raise OutreachError("IDEMPOTENCY_CONFLICT", "organization evidence conflicts")
            return existing, True
        record = ColdProspectingOrganizationEvidence(lead_id=lead_id, source_namespace=source_namespace, source_event_key=source_event_key, evidence_reference=source_record_fingerprint, evidence_fingerprint=evidence_fingerprint, request_fingerprint=request_fingerprint, source_classification=source_classification, source_record_fingerprint=source_record_fingerprint, acceptance_state="ACCEPTED", evidence_schema_version=ORGANIZATION_EVIDENCE_SCHEMA_VERSION, evaluated_at=aware_utc(evaluated_at, "evaluated_at"))
        self.db.add(record); self.db.flush(); return record, False

    def register_policy_selection(self, *, lead_id, source_namespace, source_event_key, evidence_fingerprint, profile_key, evaluated_at: datetime):
        profile = SUPPORTED_COLD_B2B_POLICY_PROFILES.get(profile_key)
        if profile is None: raise OutreachError("POLICY_UNAVAILABLE", "policy profile is not approved")
        lead_id = required_text(lead_id, "lead_id", 36); source_namespace = opaque_source_namespace(source_namespace); source_event_key = fingerprint(source_event_key, "source_event_key"); evidence_fingerprint = fingerprint(evidence_fingerprint, "policy_evidence_fingerprint")
        decision = sha256_fingerprint({"lead_id": lead_id, "evidence_fingerprint": evidence_fingerprint, "profile_key": profile.key, "profile_version": profile.version, "schema_version": POLICY_SELECTION_SCHEMA_VERSION})
        existing = self.db.query(ColdProspectingPolicySelection).filter_by(source_namespace=source_namespace, source_event_key=source_event_key).one_or_none()
        if existing is not None:
            if existing.decision_fingerprint != decision: raise OutreachError("IDEMPOTENCY_CONFLICT", "policy selection conflicts")
            return existing, True
        record = ColdProspectingPolicySelection(lead_id=lead_id, source_namespace=source_namespace, source_event_key=source_event_key, evidence_fingerprint=evidence_fingerprint, profile_key=profile.key, profile_version=profile.version, acceptance_state="ACCEPTED", selection_schema_version=POLICY_SELECTION_SCHEMA_VERSION, decision_fingerprint=decision, evaluated_at=aware_utc(evaluated_at, "evaluated_at"))
        self.db.add(record); self.db.flush(); return record, False
