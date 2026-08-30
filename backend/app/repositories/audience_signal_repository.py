"""Caller-owned persistence helpers for immutable audience signals."""
from sqlalchemy.orm import Session
from app.models.audience import AudienceEvidence, AudienceSignal, AudienceSignalEvidence


class AudienceSignalRepository:
    def __init__(self, db: Session): self.db = db
    def by_key(self, key: str): return self.db.query(AudienceSignal).filter_by(extraction_key=key).one_or_none()
    def list_for_subject(self, subject_id: str):
        return self.db.query(AudienceSignal).filter_by(subject_id=subject_id).all()
    def evidence(self, ids): return self.db.query(AudienceEvidence).filter(AudienceEvidence.id.in_(ids)).all()
    def add(self, signal): self.db.add(signal)
    def link(self, signal_id, evidence_id):
        if self.db.get(AudienceSignalEvidence, {"signal_id": signal_id, "evidence_id": evidence_id}) is None:
            self.db.add(AudienceSignalEvidence(signal_id=signal_id, evidence_id=evidence_id))
