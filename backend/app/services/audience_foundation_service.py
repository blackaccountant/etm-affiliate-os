"""Deterministic, caller-owned creation of M6.1 audience ledger records."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audience.contracts import (
    AudienceIdentityVerificationState,
    AudienceResearchRunStatus,
    AudienceSourceType,
    AudienceSubjectType,
)
from app.audience.normalization import (
    aware_utc,
    canonical_json,
    evidence_fingerprint,
    normalize_identity_reference,
    observation_key,
    required_text,
)
from app.models.audience import (
    AudienceEvidence,
    AudienceExternalIdentity,
    AudienceObservation,
    AudienceResearchRun,
    AudienceSubject,
)
from app.repositories.audience_repository import AudienceRepository


class AudienceFoundationService:
    """Create immutable audience facts without committing the caller's transaction."""

    def __init__(self, db: Session):
        self.db = db
        self.records = AudienceRepository(db)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _enum(value: object, enum_type, field: str) -> str:
        try:
            return enum_type(value).value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported {field}") from exc

    @staticmethod
    def _metadata(value: object | None, field: str = "metadata_json") -> object | None:
        if value is None:
            return None
        try:
            canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be JSON-safe") from exc
        return value

    @staticmethod
    def _same(left: object, right: object) -> bool:
        return canonical_json(left) == canonical_json(right)

    def _insert_or_existing(self, record, lookup, conflict_message: str):
        try:
            with self.db.begin_nested():
                self.db.add(record)
                self.db.flush()
            return record
        except IntegrityError:
            existing = lookup()
            if existing is not None:
                return existing
            raise RuntimeError(conflict_message)

    def create_subject(self, subject_type: str) -> AudienceSubject:
        value = self._enum(subject_type, AudienceSubjectType, "subject_type")
        subject = AudienceSubject(subject_type=value, created_at=self._now(), updated_at=self._now())
        self.db.add(subject)
        self.db.flush()
        return subject

    def attach_external_identity(self, subject_id: str, *, source_namespace: str,
                                 identity_type: str, reference: str,
                                 verification_state: str = AudienceIdentityVerificationState.UNVERIFIED.value,
                                 metadata_json: object | None = None) -> AudienceExternalIdentity:
        subject = self.records.subject(required_text(subject_id, "subject_id"))
        if subject is None:
            raise ValueError("audience subject does not exist")
        namespace = required_text(source_namespace, "source_namespace", lowercase=True)
        kind = required_text(identity_type, "identity_type", lowercase=True)
        normalized = normalize_identity_reference(kind, reference)
        verification = self._enum(verification_state, AudienceIdentityVerificationState, "verification_state")
        existing = self.records.external_identity(namespace, kind, normalized)
        if existing is not None:
            if existing.subject_id != subject.id:
                raise ValueError("external identity already belongs to another audience subject")
            return existing
        identity = AudienceExternalIdentity(
            subject_id=subject.id,
            source_namespace=namespace,
            identity_type=kind,
            normalized_reference=normalized,
            verification_state=verification,
            metadata_json=self._metadata(metadata_json),
            created_at=self._now(),
        )
        result = self._insert_or_existing(
            identity,
            lambda: self.records.external_identity(namespace, kind, normalized),
            "external identity could not be created",
        )
        if result.subject_id != subject.id:
            raise ValueError("external identity already belongs to another audience subject")
        return result

    def get_or_create_subject_for_identity(self, *, subject_type: str, source_namespace: str,
                                           identity_type: str, reference: str,
                                           verification_state: str = AudienceIdentityVerificationState.UNVERIFIED.value,
                                           metadata_json: object | None = None) -> AudienceSubject:
        namespace = required_text(source_namespace, "source_namespace", lowercase=True)
        kind = required_text(identity_type, "identity_type", lowercase=True)
        normalized = normalize_identity_reference(kind, reference)
        existing = self.records.external_identity(namespace, kind, normalized)
        if existing is not None:
            return existing.subject
        subject = AudienceSubject(
            subject_type=self._enum(subject_type, AudienceSubjectType, "subject_type"),
            created_at=self._now(), updated_at=self._now(),
        )
        identity = AudienceExternalIdentity(
            subject=subject,
            source_namespace=namespace,
            identity_type=kind,
            normalized_reference=normalized,
            verification_state=self._enum(verification_state, AudienceIdentityVerificationState, "verification_state"),
            metadata_json=self._metadata(metadata_json),
            created_at=self._now(),
        )
        result = self._insert_or_existing(
            identity,
            lambda: self.records.external_identity(namespace, kind, normalized),
            "external identity could not be created",
        )
        return result.subject

    def get_or_create_research_run(self, *, scope_type: str, scope_reference: str,
                                   idempotency_key: str, metadata_json: object | None = None) -> AudienceResearchRun:
        scope_type = required_text(scope_type, "scope_type", lowercase=True)
        scope_reference = required_text(scope_reference, "scope_reference")
        idempotency_key = required_text(idempotency_key, "idempotency_key")
        metadata_json = self._metadata(metadata_json)
        existing = self.records.research_run_by_key(idempotency_key)
        if existing is not None:
            if not self._same(
                (existing.scope_type, existing.scope_reference, existing.metadata_json),
                (scope_type, scope_reference, metadata_json),
            ):
                raise ValueError("research run idempotency key conflicts with existing intent")
            return existing
        run = AudienceResearchRun(
            scope_type=scope_type,
            scope_reference=scope_reference,
            idempotency_key=idempotency_key,
            status=AudienceResearchRunStatus.CREATED.value,
            metadata_json=metadata_json,
            created_at=self._now(),
        )
        result = self._insert_or_existing(
            run,
            lambda: self.records.research_run_by_key(idempotency_key),
            "research run could not be created",
        )
        if not self._same(
            (result.scope_type, result.scope_reference, result.metadata_json),
            (scope_type, scope_reference, metadata_json),
        ):
            raise ValueError("research run idempotency key conflicts with existing intent")
        return result

    def ingest_observation(self, *, research_run_id: str | None, subject_id: str | None,
                           source_namespace: str, source_type: str,
                           external_observation_id: str | None, source_reference: str | None,
                           observed_at: datetime, normalized_fact: object,
                           metadata_json: object | None = None) -> AudienceObservation:
        if research_run_id is not None and self.db.get(AudienceResearchRun, research_run_id) is None:
            raise ValueError("audience research run does not exist")
        if subject_id is not None and self.records.subject(subject_id) is None:
            raise ValueError("audience subject does not exist")
        namespace = required_text(source_namespace, "source_namespace", lowercase=True)
        source_kind = self._enum(source_type, AudienceSourceType, "source_type")
        observed_at = aware_utc(observed_at, "observed_at")
        metadata_json = self._metadata(metadata_json)
        key = observation_key(
            source_namespace=namespace,
            source_type=source_kind,
            external_observation_id=external_observation_id,
            source_reference=source_reference,
            observed_at=observed_at,
            normalized_fact=normalized_fact,
        )
        existing = self.records.observation_by_key(key)
        immutable = (research_run_id, subject_id, namespace, source_kind, external_observation_id,
                     source_reference, observed_at.isoformat(), normalized_fact, metadata_json)
        if existing is not None:
            stored = (existing.research_run_id, existing.subject_id, existing.source_namespace,
                      existing.source_type, existing.external_observation_id, existing.source_reference,
                      existing.observed_at.isoformat(), existing.normalized_fact, existing.metadata_json)
            if not self._same(stored, immutable):
                raise ValueError("observation key conflicts with immutable source fact")
            return existing
        observation = AudienceObservation(
            research_run_id=research_run_id,
            subject_id=subject_id,
            source_namespace=namespace,
            source_type=source_kind,
            external_observation_id=external_observation_id,
            source_reference=source_reference,
            observation_key=key,
            observed_at=observed_at,
            captured_at=self._now(),
            normalized_fact=normalized_fact,
            metadata_json=metadata_json,
        )
        result = self._insert_or_existing(
            observation,
            lambda: self.records.observation_by_key(key),
            "observation could not be created",
        )
        stored = (result.research_run_id, result.subject_id, result.source_namespace,
                  result.source_type, result.external_observation_id, result.source_reference,
                  result.observed_at.isoformat(), result.normalized_fact, result.metadata_json)
        if not self._same(stored, immutable):
            raise ValueError("observation key conflicts with immutable source fact")
        return result

    def record_evidence(self, *, observation_id: str, source_reference: str,
                        normalized_representation: object, content_fingerprint: str | None = None,
                        source_uri: str | None = None, excerpt: str | None = None,
                        metadata_json: object | None = None) -> AudienceEvidence:
        observation_id = required_text(observation_id, "observation_id")
        if self.db.get(AudienceObservation, observation_id) is None:
            raise ValueError("audience observation does not exist")
        source_reference = required_text(source_reference, "source_reference")
        metadata_json = self._metadata(metadata_json)
        fingerprint = evidence_fingerprint(
            observation_id=observation_id,
            source_reference=source_reference,
            normalized_representation=normalized_representation,
            content_fingerprint=content_fingerprint,
        )
        existing = self.records.evidence_by_fingerprint(observation_id, fingerprint)
        immutable = (source_reference, source_uri, excerpt, normalized_representation, content_fingerprint, metadata_json)
        if existing is not None:
            stored = (existing.source_reference, existing.source_uri, existing.excerpt,
                      existing.normalized_representation, existing.content_fingerprint, existing.metadata_json)
            if not self._same(stored, immutable):
                raise ValueError("evidence fingerprint conflicts with immutable provenance")
            return existing
        evidence = AudienceEvidence(
            observation_id=observation_id,
            source_reference=source_reference,
            source_uri=source_uri,
            captured_at=self._now(),
            excerpt=excerpt,
            normalized_representation=normalized_representation,
            content_fingerprint=content_fingerprint,
            evidence_fingerprint=fingerprint,
            metadata_json=metadata_json,
        )
        result = self._insert_or_existing(
            evidence,
            lambda: self.records.evidence_by_fingerprint(observation_id, fingerprint),
            "evidence could not be created",
        )
        stored = (result.source_reference, result.source_uri, result.excerpt,
                  result.normalized_representation, result.content_fingerprint, result.metadata_json)
        if not self._same(stored, immutable):
            raise ValueError("evidence fingerprint conflicts with immutable provenance")
        return result
