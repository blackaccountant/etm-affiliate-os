"""Atomic B2 creation of a commercial cold operation and its bound content."""
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from app.models.cold_delivery import ColdDeliveryOperation, ColdDeliveryOperationState, ColdMessageContent
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.outreach.contracts import OutreachError, PreparedOutreachMessage, sha256_fingerprint
from app.outreach.cold_b2b_contracts import opaque_source_namespace
from app.outreach.cold_delivery_contracts import ColdMessageContentContract
from app.repositories.cold_prospecting_repository import ColdProspectingRepository

@dataclass(frozen=True)
class ColdDeliveryOperationCreation:
    cold_authorization_id: str; source_namespace: str; source_event_key: str; message: PreparedOutreachMessage

@dataclass(frozen=True)
class ColdDeliveryOperationCreationResult:
    operation: ColdDeliveryOperation; content: ColdMessageContent; reused: bool

class ColdDeliveryOperationService:
    def __init__(self, db): self.db = db
    def create_or_reuse(self, request):
        if not isinstance(request, ColdDeliveryOperationCreation): raise OutreachError("INVALID_CONTRACT", "invalid cold operation request")
        content = ColdMessageContentContract(request.message)
        namespace = opaque_source_namespace(request.source_namespace)
        key = sha256_fingerprint({"source_event_key": request.source_event_key}) if len(request.source_event_key) != 64 else request.source_event_key
        locks = ColdProspectingRepository(self.db); locks.acquire_lock("cold-delivery-source-v1", namespace + "\x00" + key)
        auth = self.db.get(ColdProspectingAuthorization, request.cold_authorization_id)
        if auth is None or auth.authorization_state != "ELIGIBLE": raise OutreachError("AUTHORIZATION_UNAVAILABLE", "eligible cold authorization is required")
        fingerprint = content.content_fingerprint
        existing = self.db.query(ColdDeliveryOperation).filter_by(source_namespace=namespace, source_event_key=key).one_or_none()
        if existing is not None:
            if existing.cold_authorization_id != auth.id or existing.message_content_fingerprint != fingerprint: raise OutreachError("IDEMPOTENCY_CONFLICT", "cold delivery source conflicts with immutable inputs")
            stored = self.db.query(ColdMessageContent).filter_by(operation_id=existing.id).one()
            return ColdDeliveryOperationCreationResult(existing, stored, True)
        try:
            # A savepoint makes the three-record commercial creation indivisible
            # without rolling back unrelated caller work on a deterministic race.
            with self.db.begin_nested():
                operation = ColdDeliveryOperation(cold_authorization_id=auth.id, lead_id=auth.lead_id, contact_point_id=auth.contact_point_id, action=auth.requested_action, purpose_key=auth.purpose_key, purpose_family=auth.purpose_family, source_namespace=namespace, source_event_key=key, message_content_fingerprint=fingerprint, operation_schema_version="cold-delivery-operation-v1", created_at=datetime.now(timezone.utc))
                self.db.add(operation); self.db.flush()
                stored = ColdMessageContent(operation_id=operation.id, content_fingerprint=fingerprint, subject=request.message.subject, body=request.message.body, content_format=request.message.content_format, content_schema_version="cold-message-content-v1", created_at=datetime.now(timezone.utc))
                self.db.add(stored); self.db.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="CREATED", revision=1, next_event_sequence=1, updated_at=datetime.now(timezone.utc))); self.db.flush()
            return ColdDeliveryOperationCreationResult(operation, stored, False)
        except IntegrityError as error:
            # The unique source identity is the final race boundary.  Re-read it
            # and turn a compatible replay into reuse, never a raw IntegrityError.
            existing = self.db.query(ColdDeliveryOperation).filter_by(source_namespace=namespace, source_event_key=key).one_or_none()
            if existing is None:
                raise OutreachError("OPERATION_CREATION_FAILED", "cold delivery operation creation failed") from error
            if existing.cold_authorization_id != auth.id or existing.message_content_fingerprint != fingerprint:
                raise OutreachError("IDEMPOTENCY_CONFLICT", "cold delivery source conflicts with immutable inputs") from error
            return ColdDeliveryOperationCreationResult(existing, self.db.query(ColdMessageContent).filter_by(operation_id=existing.id).one(), True)
