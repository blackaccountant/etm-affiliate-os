"""Validation and caller-owned persistence for proposed audience signals."""
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.audience.contracts import AudienceIntentStage, AudienceSignalError, AudienceSignalType
from app.audience.normalization import aware_utc, canonical_json, evidence_set_fingerprint, normalize_topic, required_text, signal_extraction_key
from app.models.audience import AudienceSignal
from app.repositories.audience_signal_repository import AudienceSignalRepository

@dataclass(frozen=True)
class SignalCandidate:
    signal_type: str; topic: str; topic_label: str; intent_stage: str | None; strength: int; confidence: int; evidence_ids: list[str]; ruleset_version: str
    model_version: str | None = None; rationale: str | None = None; metadata_json: object | None = None; observed_purchase: bool = False; expires_at: datetime | None = None; supersedes_signal_id: str | None = None

class AudienceSignalService:
    def __init__(self, db: Session): self.db, self.records = db, AudienceSignalRepository(db)
    def persist_many(self, candidates, *, subject_id=None): return [self.persist(candidate, subject_id=subject_id) for candidate in candidates]
    def _fail(self, category, message): raise AudienceSignalError(category, message)
    def persist(self, candidate: SignalCandidate, *, subject_id: str | None = None) -> AudienceSignal:
        try: kind = AudienceSignalType(candidate.signal_type).value
        except ValueError: self._fail("UNSUPPORTED_SIGNAL", "unsupported signal type")
        stage = candidate.intent_stage
        if (kind == "INTENT") != (stage is not None): self._fail("UNSUPPORTED_SIGNAL", "intent stage is permitted only for INTENT")
        if stage is not None:
            try: stage = AudienceIntentStage(stage).value
            except ValueError: self._fail("UNSUPPORTED_SIGNAL", "unsupported intent stage")
        if kind == "PURCHASE" and not candidate.observed_purchase: self._fail("INVALID_EVIDENCE", "purchase requires observed behavior")
        if not isinstance(candidate.strength, int) or isinstance(candidate.strength, bool) or not 0 <= candidate.strength <= 100: self._fail("INVALID_STRENGTH", "strength must be 0..100")
        if not isinstance(candidate.confidence, int) or isinstance(candidate.confidence, bool) or not 0 <= candidate.confidence <= 100: self._fail("INVALID_CONFIDENCE", "confidence must be 0..100")
        slug, label = normalize_topic(candidate.topic, candidate.topic_label)
        if any(term in slug for term in ("religion", "race", "ethnicity", "political", "health", "sexual-orientation")): self._fail("SENSITIVE_SIGNAL_BLOCKED", "sensitive targeting signal blocked")
        if candidate.rationale is not None and (not isinstance(candidate.rationale, str) or len(candidate.rationale) > 1000): self._fail("INVALID_PROVIDER_OUTPUT", "rationale is invalid")
        try:
            ruleset = required_text(candidate.ruleset_version, "ruleset_version")
        except ValueError as exc:
            self._fail("INVALID_PROVIDER_OUTPUT", "ruleset_version is required")
        evidence = self.records.evidence(list(dict.fromkeys(candidate.evidence_ids)))
        if len(evidence) != len(set(candidate.evidence_ids)): self._fail("INVALID_EVIDENCE", "all evidence must exist")
        observation_subjects = {item.observation.subject_id for item in evidence}
        if subject_id is None:
            if observation_subjects != {None}: self._fail("LINEAGE_CONFLICT", "subjectless signal requires subjectless evidence")
        elif observation_subjects != {subject_id}: self._fail("LINEAGE_CONFLICT", "evidence subject lineage conflicts")
        if kind == "BUSINESS_NEED":
            subject = self.db.get(__import__("app.models.audience", fromlist=["AudienceSubject"]).AudienceSubject, subject_id) if subject_id else None
            if subject_id is not None and (subject is None or subject.subject_type != "ORGANIZATION"): self._fail("LINEAGE_CONFLICT", "business need requires organization or subjectless evidence")
        cap = 100 if len(evidence) >= 2 or all(item.observation.source_type.startswith("FIRST_PARTY") for item in evidence) else 60
        if candidate.confidence > cap: self._fail("INVALID_CONFIDENCE", "confidence exceeds evidence-quality cap")
        fingerprint = evidence_set_fingerprint([(item.id, item.evidence_fingerprint) for item in evidence])
        key = signal_extraction_key(subject_id=subject_id, signal_type=kind, topic_slug=slug, intent_stage=stage, evidence_set=fingerprint, ruleset_version=ruleset)
        existing = self.records.by_key(key)
        immutable = (subject_id, kind, slug, label, stage, candidate.strength, candidate.confidence, fingerprint, ruleset, candidate.model_version, candidate.rationale)
        if existing is not None:
            stored = (existing.subject_id, existing.signal_type, existing.topic_slug, existing.topic_label, existing.intent_stage, existing.strength, existing.confidence, existing.evidence_set_fingerprint, existing.ruleset_version, existing.model_version, existing.rationale)
            if canonical_json(stored) != canonical_json(immutable): self._fail("CANDIDATE_CONFLICT", "extraction key conflicts with immutable signal")
            return existing
        observed = max(item.observation.observed_at for item in evidence)
        expires = aware_utc(candidate.expires_at, "expires_at") if candidate.expires_at else None
        if expires and expires < observed: self._fail("INVALID_PROVIDER_OUTPUT", "expires_at precedes observed_at")
        predecessor = self.db.get(AudienceSignal, candidate.supersedes_signal_id) if candidate.supersedes_signal_id else None
        if candidate.supersedes_signal_id and predecessor is None: self._fail("INVALID_EVIDENCE", "superseded signal does not exist")
        if predecessor is not None and (predecessor.id == key or predecessor.subject_id != subject_id or predecessor.signal_type != kind or predecessor.topic_slug != slug):
            self._fail("CANDIDATE_CONFLICT", "supersession must retain conceptual scope")
        signal = AudienceSignal(subject_id=subject_id, signal_type=kind, topic_slug=slug, topic_label=label, intent_stage=stage, strength=candidate.strength, confidence=candidate.confidence, evidence_set_fingerprint=fingerprint, extraction_key=key, ruleset_version=ruleset, model_version=candidate.model_version, observed_at=observed, derived_at=datetime.now(timezone.utc), expires_at=expires, supersedes_signal_id=candidate.supersedes_signal_id, rationale=candidate.rationale, metadata_json=candidate.metadata_json)
        try:
            with self.db.begin_nested():
                self.records.add(signal); self.db.flush()
                for item in evidence: self.records.link(signal.id, item.id)
                self.db.flush()
        except IntegrityError:
            existing = self.records.by_key(key)
            if existing is None: raise
            return existing
        return signal
