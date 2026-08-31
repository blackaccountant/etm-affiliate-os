"""Caller-session persistence for immutable M9C1 provider facts."""

from dataclasses import dataclass

from app.models.outreach_provider_dispatch import OutreachProviderDispatch, OutreachProviderReference
from app.outreach.contracts import OutreachError


@dataclass(frozen=True)
class ProviderPersistenceResult:
    record: object
    reused: bool


class OutreachProviderDispatchRepository:
    def __init__(self, db):
        self.db = db

    def by_attempt(self, delivery_attempt_id: str) -> OutreachProviderDispatch | None:
        return self.db.query(OutreachProviderDispatch).filter_by(
            delivery_attempt_id=delivery_attempt_id,
        ).one_or_none()

    def by_operation(self, provider_key: str, provider_operation_key: str) -> OutreachProviderDispatch | None:
        return self.db.query(OutreachProviderDispatch).filter_by(
            provider_key=provider_key, provider_operation_key=provider_operation_key,
        ).one_or_none()

    def create_or_reuse(self, proposed: OutreachProviderDispatch) -> ProviderPersistenceResult:
        existing = self.by_attempt(proposed.delivery_attempt_id)
        if existing is None:
            existing = self.by_operation(proposed.provider_key, proposed.provider_operation_key)
        if existing is not None:
            return self._same_dispatch(existing, proposed)
        self.db.add(proposed)
        self.db.flush()
        return ProviderPersistenceResult(proposed, False)

    @staticmethod
    def _same_dispatch(existing: OutreachProviderDispatch, proposed: OutreachProviderDispatch) -> ProviderPersistenceResult:
        identity_fields = (
            "delivery_attempt_id", "provider_key", "provider_contract_version",
            "provider_operation_key", "provider_operation_fingerprint",
        )
        if any(getattr(existing, field) != getattr(proposed, field) for field in identity_fields):
            raise OutreachError("PROVIDER_OPERATION_CONFLICT", "provider operation identity conflicts")
        if existing.sender_identity_fingerprint != proposed.sender_identity_fingerprint:
            raise OutreachError("CONFIGURATION_DRIFT", "provider sender configuration drift")
        if existing.provider_payload_fingerprint != proposed.provider_payload_fingerprint:
            raise OutreachError("PROVIDER_PAYLOAD_DRIFT", "provider-visible payload drift")
        return ProviderPersistenceResult(existing, True)

    def reference_for_dispatch(self, provider_dispatch_id: str) -> OutreachProviderReference | None:
        return self.db.query(OutreachProviderReference).filter_by(
            provider_dispatch_id=provider_dispatch_id,
        ).one_or_none()

    def reference_by_provider(self, provider_key: str, provider_reference: str) -> OutreachProviderReference | None:
        return self.db.query(OutreachProviderReference).filter_by(
            provider_key=provider_key, provider_reference=provider_reference,
        ).one_or_none()

    def add_reference_or_reuse(self, proposed: OutreachProviderReference) -> ProviderPersistenceResult:
        existing = self.reference_for_dispatch(proposed.provider_dispatch_id)
        if existing is None:
            existing = self.reference_by_provider(proposed.provider_key, proposed.provider_reference)
        if existing is not None:
            if (
                existing.provider_dispatch_id != proposed.provider_dispatch_id
                or existing.provider_key != proposed.provider_key
                or existing.provider_reference != proposed.provider_reference
            ):
                raise OutreachError("PROVIDER_REFERENCE_CONFLICT", "provider reference conflicts")
            return ProviderPersistenceResult(existing, True)
        self.db.add(proposed)
        self.db.flush()
        return ProviderPersistenceResult(proposed, False)
