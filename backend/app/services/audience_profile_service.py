"""Caller-owned immutable profile derivation from durable audience signals."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.audience.contracts import AudienceSubjectType
from app.audience.normalization import aware_utc
from app.audience.profile_contracts import PROFILE_RULESET_VERSION, profile_source_fingerprint
from app.audience.profile_derivation import AudienceProfileDerivationError, effective_signals, profile_summary
from app.models.audience import AudienceProfile, AudienceSubject
from app.repositories.audience_profile_repository import AudienceProfileRepository
from app.repositories.audience_signal_repository import AudienceSignalRepository


@dataclass(frozen=True)
class AudienceProfileDerivationResult:
    profile_id: str
    subject_id: str
    profile_ruleset_version: str
    source_fingerprint: str
    effective_signal_ids: tuple[str, ...]


class AudienceProfileService:
    """Derive one immutable snapshot; callers retain transaction ownership."""

    def __init__(self, db: Session):
        self.db = db
        self.profiles = AudienceProfileRepository(db)
        self.signals = AudienceSignalRepository(db)

    def derive(self, subject_id: str, *, effective_as_of: datetime,
               profile_ruleset_version: str = PROFILE_RULESET_VERSION) -> AudienceProfileDerivationResult:
        as_of = aware_utc(effective_as_of, "effective_as_of")
        subject = self.db.get(AudienceSubject, subject_id)
        if subject is None:
            raise AudienceProfileDerivationError("SUBJECT_NOT_FOUND", "audience subject does not exist")
        try:
            AudienceSubjectType(subject.subject_type)
        except ValueError as exc:
            raise AudienceProfileDerivationError("INVALID_SUBJECT", "unsupported audience subject type") from exc
        if profile_ruleset_version != PROFILE_RULESET_VERSION:
            raise AudienceProfileDerivationError("UNSUPPORTED_PROFILE_RULESET", "unsupported profile ruleset")
        selected = effective_signals(self.signals.list_for_subject(subject.id), effective_as_of=as_of)
        signal_ids = tuple(signal.id for signal in selected)
        fingerprint = profile_source_fingerprint(
            subject.id,
            profile_ruleset_version,
            [(signal.id, signal.extraction_key) for signal in selected],
        )
        profile = AudienceProfile(
            subject_id=subject.id,
            profile_ruleset_version=profile_ruleset_version,
            source_fingerprint=fingerprint,
            effective_as_of=as_of,
            last_signal_observed_at=max((signal.observed_at for signal in selected), default=None),
            summary_json=profile_summary(selected),
        )
        stored = self.profiles.create_or_reuse(profile, signal_ids)
        return AudienceProfileDerivationResult(
            profile_id=stored.id,
            subject_id=stored.subject_id,
            profile_ruleset_version=stored.profile_ruleset_version,
            source_fingerprint=stored.source_fingerprint,
            effective_signal_ids=signal_ids,
        )
