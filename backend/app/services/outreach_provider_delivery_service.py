"""Fenced, crash-safe orchestration of one consented Resend operation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.outreach_delivery import OutreachDeliveryEvent
from app.models.outreach_provider_dispatch import OutreachProviderDispatch, OutreachProviderReference
from app.outreach.contracts import OutreachError, aware_utc, sha256_fingerprint
from app.outreach.delivery_contracts import DeliveryEventType
from app.outreach.provider_contracts import (
    ProviderFailureCategory,
    ProviderSendOutcome,
    ProviderSendRequest,
    RESEND_CONTRACT_VERSION,
    RESEND_PROVIDER_KEY,
    RESEND_SAFE_REPLAY_HOURS,
    provider_operation_fingerprint,
    provider_operation_key,
)
from app.outreach.provider_failure_adapter import ProviderFailureAdapter
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.outreach_delivery_attempt_repository import OutreachDeliveryAttemptRepository
from app.repositories.outreach_delivery_event_repository import OutreachDeliveryEventRepository
from app.repositories.outreach_message_repository import OutreachMessageRepository
from app.repositories.outreach_provider_dispatch_repository import OutreachProviderDispatchRepository
from app.services.outreach_intent_service import OutreachIntentService
from app.services.outreach_recipient_resolution_service import OutreachRecipientResolutionService


M9C1_EVENT_TYPES = (
    "AUTHORIZATION_BLOCKED", "DISPATCH_PLANNED", "DISPATCH_STARTED", "DISPATCH_DEFERRED",
    "PROVIDER_ACCEPTED", "PROVIDER_REJECTED", "PROVIDER_AMBIGUOUS",
)
TERMINAL_EVENT_TYPES = ("PROVIDER_ACCEPTED", "PROVIDER_REJECTED", "PROVIDER_AMBIGUOUS")


@dataclass(frozen=True)
class OutreachProviderDeliveryResult:
    delivery_attempt_id: str
    outcome: str
    provider_key: str = RESEND_PROVIDER_KEY
    provider_reference: str | None = None
    retryable: bool = False
    safe_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        values = {
            "delivery_attempt_id": self.delivery_attempt_id,
            "outcome": self.outcome,
            "provider_key": self.provider_key,
            "retryable": self.retryable,
        }
        if self.provider_reference is not None:
            values["provider_reference"] = self.provider_reference
        if self.safe_message is not None:
            values["safe_message"] = self.safe_message
        return values


class OutreachProviderDeliveryService:
    def __init__(self, db, provider_registry, *, clock=None):
        self.db = db
        self.provider_registry = provider_registry
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.attempts = OutreachDeliveryAttemptRepository(db)
        self.events = OutreachDeliveryEventRepository(db)
        self.messages = OutreachMessageRepository(db)
        self.dispatches = OutreachProviderDispatchRepository(db)

    def _now(self) -> datetime:
        return aware_utc(self.clock(), "current_time")

    def _event(self, attempt_id: str, event_type: str, occurred_at: datetime,
               safe_payload: dict[str, object]) -> OutreachDeliveryEvent:
        if event_type not in M9C1_EVENT_TYPES:
            raise OutreachError("INVALID_EVENT_TYPE", "event type is not part of M9C1")
        existing = next((item for item in self.events.list_ordered(attempt_id) if item.event_type == event_type), None)
        if existing is not None:
            return existing
        sequence = max((item.sequence_number for item in self.events.list_ordered(attempt_id)), default=0) + 1
        namespace = "outreach-delivery"
        source_key = f"{attempt_id}:{event_type.lower()}"
        fingerprint = sha256_fingerprint({
            "delivery_attempt_id": attempt_id, "event_type": event_type,
            "occurred_at": occurred_at.isoformat(), "safe_payload": safe_payload,
            "sequence_number": sequence,
        })
        return self.events.append_or_reuse(OutreachDeliveryEvent(
            delivery_attempt_id=attempt_id, sequence_number=sequence, event_type=event_type,
            occurred_at=occurred_at, source_namespace=namespace, source_event_key=source_key,
            event_fingerprint=fingerprint, safe_payload=safe_payload,
        )).record

    def _terminal(self, attempt_id: str) -> OutreachProviderDeliveryResult | None:
        for event in self.events.list_ordered(attempt_id):
            if event.event_type in TERMINAL_EVENT_TYPES:
                reference = None
                dispatch = self.dispatches.by_attempt(attempt_id)
                if dispatch is not None:
                    stored = self.dispatches.reference_for_dispatch(dispatch.id)
                    reference = stored.provider_reference if stored is not None else None
                return OutreachProviderDeliveryResult(attempt_id, event.event_type, provider_reference=reference)
        return None

    def _require_prepared(self, attempt_id: str) -> None:
        prepared = self.events.by_attempt_sequence(attempt_id, 1)
        if prepared is None or prepared.event_type != DeliveryEventType.PREPARED.value:
            raise OutreachError("MISSING_PREPARED", "delivery attempt has no valid PREPARED event")

    def deliver(self, delivery_attempt_id: str, authority) -> OutreachProviderDeliveryResult:
        attempt = self.attempts.get(delivery_attempt_id)
        if attempt is None:
            raise OutreachError("ATTEMPT_NOT_FOUND", "delivery attempt does not exist")
        terminal = self._terminal(attempt.id)
        if terminal is not None:
            self.db.rollback()
            return terminal
        self._require_prepared(attempt.id)
        intent = attempt.intent
        message = self.messages.by_intent(intent.id)
        if message is None:
            raise OutreachError("INCOMPLETE_INTENT", "outreach intent has no immutable message")
        now = self._now()
        existing_dispatch = self.dispatches.by_attempt(attempt.id)
        if existing_dispatch is not None:
            started = aware_utc(existing_dispatch.dispatch_started_at, "dispatch_started_at")
            elapsed = now - started
            if elapsed.total_seconds() < 0 or elapsed.total_seconds() >= RESEND_SAFE_REPLAY_HOURS * 3600:
                ExecutionRepository(self.db).verify_active_authority(authority)
                self._event(attempt.id, "PROVIDER_AMBIGUOUS", now, {
                    "provider_key": RESEND_PROVIDER_KEY, "reason": "REPLAY_HORIZON_EXPIRED",
                    "reconciliation_required": True,
                })
                self.db.commit()
                return OutreachProviderDeliveryResult(
                    attempt.id, "PROVIDER_AMBIGUOUS", safe_message="provider result requires reconciliation",
                )

        eligibility = OutreachIntentService(self.db).revalidate_for_execution(intent.id, now)
        if not eligibility.eligible:
            ExecutionRepository(self.db).verify_active_authority(authority)
            self._event(attempt.id, "AUTHORIZATION_BLOCKED", now, {
                "eligibility": eligibility.state, "reason_codes": list(eligibility.reason_codes),
            })
            self.db.commit()
            return OutreachProviderDeliveryResult(attempt.id, "AUTHORIZATION_BLOCKED")

        ExecutionRepository(self.db).verify_active_authority(authority)
        provider = self.provider_registry.resolve(RESEND_PROVIDER_KEY, intent.channel)
        recipient = OutreachRecipientResolutionService(self.db).resolve_email(
            lead_id=intent.lead_id, contact_point_id=intent.contact_point_id, channel=intent.channel,
        )
        operation_key = provider_operation_key(attempt.id)
        request = ProviderSendRequest(
            operation_key, provider.sender_identity, recipient, message.subject, message.body, message.content_format,
        )
        proposed = OutreachProviderDispatch(
            delivery_attempt_id=attempt.id,
            provider_key=RESEND_PROVIDER_KEY,
            provider_contract_version=RESEND_CONTRACT_VERSION,
            provider_operation_key=operation_key,
            provider_operation_fingerprint=provider_operation_fingerprint(attempt.id, operation_key),
            provider_payload_fingerprint=request.provider_payload_fingerprint,
            sender_identity_fingerprint=request.sender_identity_fingerprint,
            planned_at=now,
            dispatch_started_at=now,
        )
        dispatch = self.dispatches.create_or_reuse(proposed).record
        self._event(attempt.id, "DISPATCH_PLANNED", dispatch.planned_at, {
            "provider_key": dispatch.provider_key,
            "provider_contract_version": dispatch.provider_contract_version,
            "provider_dispatch_id": dispatch.id,
        })
        self._event(attempt.id, "DISPATCH_STARTED", dispatch.dispatch_started_at, {
            "provider_key": dispatch.provider_key, "provider_dispatch_id": dispatch.id,
        })
        self.db.commit()

        # End the authority-check transaction before crossing the network boundary.
        ExecutionRepository(self.db).verify_active_authority(authority)
        self.db.commit()
        provider_result = provider.send(request)

        ExecutionRepository(self.db).verify_active_authority(authority)
        outcome = provider_result.outcome
        failure = provider_result.failure
        if outcome is ProviderSendOutcome.DEFINITELY_ACCEPTED:
            reference = self.dispatches.add_reference_or_reuse(OutreachProviderReference(
                provider_dispatch_id=dispatch.id, provider_key=RESEND_PROVIDER_KEY,
                provider_reference=provider_result.provider_reference,
            )).record
            self._event(attempt.id, "PROVIDER_ACCEPTED", self._now(), {
                "provider_key": RESEND_PROVIDER_KEY, "provider_dispatch_id": dispatch.id,
                "provider_reference_id": reference.id,
            })
            self.db.commit()
            return OutreachProviderDeliveryResult(
                attempt.id, "PROVIDER_ACCEPTED", provider_reference=reference.provider_reference,
            )
        if outcome is ProviderSendOutcome.DEFINITELY_REJECTED:
            self._event(attempt.id, "PROVIDER_REJECTED", self._now(), {
                "provider_key": RESEND_PROVIDER_KEY,
                "safe_code": failure.safe_code if failure else "PROVIDER_REJECTED_REQUEST",
            })
            self.db.commit()
            return OutreachProviderDeliveryResult(attempt.id, "PROVIDER_REJECTED")
        if outcome is ProviderSendOutcome.AMBIGUOUS or (
            failure and failure.category is ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT
        ):
            self._event(attempt.id, "PROVIDER_AMBIGUOUS", self._now(), {
                "provider_key": RESEND_PROVIDER_KEY,
                "safe_code": failure.safe_code if failure else "PROVIDER_RESULT_AMBIGUOUS",
                "reconciliation_required": True,
            })
            self.db.commit()
            return OutreachProviderDeliveryResult(
                attempt.id, "PROVIDER_AMBIGUOUS", safe_message="provider result requires reconciliation",
            )
        if failure and failure.category is ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT:
            self._event(attempt.id, "DISPATCH_DEFERRED", self._now(), {
                "provider_key": RESEND_PROVIDER_KEY, "safe_code": failure.safe_code,
            })
            self.db.commit()
            return OutreachProviderDeliveryResult(
                attempt.id, "DISPATCH_DEFERRED", retryable=True,
                safe_message=ProviderFailureAdapter.classifier_text(failure),
            )
        self._event(attempt.id, "PROVIDER_REJECTED", self._now(), {
            "provider_key": RESEND_PROVIDER_KEY,
            "safe_code": failure.safe_code if failure else "PROVIDER_CONTRACT_FAILURE",
        })
        self.db.commit()
        return OutreachProviderDeliveryResult(
            attempt.id, "PROVIDER_REJECTED",
            safe_message=ProviderFailureAdapter.classifier_text(failure) if failure else "provider contract failure",
        )
