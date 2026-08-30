"""Caller-owned persistence helpers for the M6.1 audience foundation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audience import (
    AudienceEvidence,
    AudienceExternalIdentity,
    AudienceObservation,
    AudienceResearchRun,
    AudienceSubject,
)


class AudienceRepository:
    def __init__(self, db: Session):
        self.db = db

    def research_run_by_key(self, idempotency_key: str) -> AudienceResearchRun | None:
        return self.db.query(AudienceResearchRun).filter_by(idempotency_key=idempotency_key).one_or_none()

    def external_identity(self, source_namespace: str, identity_type: str,
                          normalized_reference: str) -> AudienceExternalIdentity | None:
        return (
            self.db.query(AudienceExternalIdentity)
            .filter_by(
                source_namespace=source_namespace,
                identity_type=identity_type,
                normalized_reference=normalized_reference,
            )
            .one_or_none()
        )

    def observation_by_key(self, observation_key: str) -> AudienceObservation | None:
        return self.db.query(AudienceObservation).filter_by(observation_key=observation_key).one_or_none()

    def research_run(self, research_run_id: str) -> AudienceResearchRun | None:
        return self.db.get(AudienceResearchRun, research_run_id)

    def observation(self, observation_id: str) -> AudienceObservation | None:
        return self.db.get(AudienceObservation, observation_id)

    def evidence_for_observation(self, observation_id: str) -> list[AudienceEvidence]:
        return (
            self.db.query(AudienceEvidence)
            .filter_by(observation_id=observation_id)
            .order_by(AudienceEvidence.id.asc())
            .all()
        )

    def evidence_for_snapshot(self, observation_id: str,
                              evidence_ids: tuple[str, ...]) -> list[AudienceEvidence]:
        records = (
            self.db.query(AudienceEvidence)
            .filter(AudienceEvidence.observation_id == observation_id)
            .filter(AudienceEvidence.id.in_(evidence_ids))
            .order_by(AudienceEvidence.id.asc())
            .all()
        )
        if tuple(record.id for record in records) != tuple(sorted(evidence_ids)):
            return []
        return records

    def evidence_by_fingerprint(self, observation_id: str,
                                evidence_fingerprint: str) -> AudienceEvidence | None:
        return (
            self.db.query(AudienceEvidence)
            .filter_by(observation_id=observation_id, evidence_fingerprint=evidence_fingerprint)
            .one_or_none()
        )

    def subject(self, subject_id: str) -> AudienceSubject | None:
        return self.db.get(AudienceSubject, subject_id)
