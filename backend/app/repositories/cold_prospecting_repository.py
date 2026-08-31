"""Caller-owned persistence and PostgreSQL advisory locks for M9C2A."""

import hashlib

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.cold_prospecting import ColdProspectingAuthorization, ColdProspectingOrganizationEvidence, ColdProspectingPolicySelection
from app.outreach.contracts import OutreachError


def advisory_lock_key(namespace, identity):
    digest = hashlib.sha256(f"{namespace}\x00{identity}".encode("utf-8")).digest()[:8]
    value = int.from_bytes(digest, "big", signed=False)
    return value - (1 << 64) if value >= (1 << 63) else value


class ColdProspectingRepository:
    def __init__(self, db): self.db = db

    def acquire_lock(self, namespace, identity):
        if self.db.bind.dialect.name == "sqlite": return
        self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_lock_key(namespace, identity)})

    def evidence(self, identifier): return self.db.get(ColdProspectingOrganizationEvidence, identifier)
    def policy_selection(self, identifier): return self.db.get(ColdProspectingPolicySelection, identifier)
    def authorization_by_source(self, namespace, key): return self.db.query(ColdProspectingAuthorization).filter_by(source_namespace=namespace, source_event_key=key).one_or_none()

    def create_authorization_or_reuse(self, proposed):
        try:
            with self.db.begin_nested():
                self.db.add(proposed); self.db.flush()
            return proposed, False
        except IntegrityError:
            existing = self.authorization_by_source(proposed.source_namespace, proposed.source_event_key)
            if existing is None: raise
            if existing.request_fingerprint != proposed.request_fingerprint: raise OutreachError("IDEMPOTENCY_CONFLICT", "cold authorization conflicts")
            return existing, True

    def bounded_eligible_history(self, *, lead_id, contact_point_id, purpose_family, limit):
        return self.db.query(ColdProspectingAuthorization).filter_by(lead_id=lead_id, contact_point_id=contact_point_id, channel="EMAIL", purpose_family=purpose_family, authorization_state="ELIGIBLE").order_by(ColdProspectingAuthorization.evaluated_at.desc(), ColdProspectingAuthorization.id.desc()).limit(limit).all()
