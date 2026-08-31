"""Pure M9C1 provider identity, capability, registry, and privacy proofs."""

from datetime import timedelta

import pytest

from app.outreach.contracts import OutreachError
from app.outreach.provider_contracts import (
    EphemeralRecipient, ProviderCapabilities, ProviderFailure, ProviderFailureCategory,
    ProviderSendOutcome, ProviderSendRequest, ProviderSendResult,
    RESEND_CONTRACT_VERSION, RESEND_PROVIDER_KEY, provider_operation_fingerprint,
    provider_operation_key,
)
from app.outreach.provider_registry import OutreachProviderRegistry


class Provider:
    capabilities = ProviderCapabilities(
        "resend", "resend-email-v1", ("EMAIL",), True,
        timedelta(hours=24), timedelta(hours=23), True,
    )
    sender_identity = "Sender <sender@example.com>"
    def send(self, request):
        return ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque")


def test_resend_capabilities_freeze_email_idempotency_and_safe_horizon():
    capabilities = Provider().capabilities
    assert capabilities.provider_key == RESEND_PROVIDER_KEY == "resend"
    assert capabilities.provider_contract_version == RESEND_CONTRACT_VERSION == "resend-email-v1"
    assert capabilities.channels == ("EMAIL",) and capabilities.native_idempotency is True
    assert capabilities.documented_idempotency_retention == timedelta(hours=24)
    assert capabilities.safe_replay_horizon == timedelta(hours=23)
    assert capabilities.supports_provider_reference is True


def test_operation_identity_is_stable_and_excludes_execution_recipient_and_body():
    attempt = "11111111-1111-1111-1111-111111111111"
    key = provider_operation_key(attempt)
    assert key == f"outreach-delivery/{attempt}/resend-email-v1"
    assert key == provider_operation_key(attempt)
    assert "recipient@example.com" not in key and "Execution" not in key and "body" not in key
    assert provider_operation_fingerprint(attempt, key) == provider_operation_fingerprint(attempt, key)
    assert len(provider_operation_fingerprint(attempt, key)) == 64


def test_payload_and_sender_fingerprints_are_deterministic_but_pii_is_not_exposed_by_repr():
    recipient = EphemeralRecipient("EMAIL", "recipient@example.com")
    request = ProviderSendRequest("operation", "Sender <sender@example.com>", recipient, "Subject", "Body", "TEXT")
    same = ProviderSendRequest("operation", "Sender <sender@example.com>", recipient, "Subject", "Body", "TEXT")
    changed = ProviderSendRequest("operation", "Sender <sender@example.com>", EphemeralRecipient("EMAIL", "other@example.com"), "Subject", "Body", "TEXT")
    assert request.provider_payload_fingerprint == same.provider_payload_fingerprint
    assert request.provider_payload_fingerprint != changed.provider_payload_fingerprint
    assert request.sender_identity_fingerprint == same.sender_identity_fingerprint
    assert "recipient@example.com" not in repr(recipient) + repr(request)
    assert "Body" not in repr(request)


def test_outcomes_and_failures_are_explicit_and_raw_exceptions_are_not_contract_values():
    accepted = ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, "opaque-id")
    rejected = ProviderSendResult(ProviderSendOutcome.DEFINITELY_REJECTED)
    ambiguous = ProviderSendResult(
        ProviderSendOutcome.AMBIGUOUS,
        failure=ProviderFailure(ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, "SAFE"),
    )
    deferred = ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "SAFE")
    assert accepted.provider_reference == "opaque-id"
    assert rejected.outcome is ProviderSendOutcome.DEFINITELY_REJECTED
    assert ambiguous.outcome is ProviderSendOutcome.AMBIGUOUS
    assert deferred.retryable is True


def test_registry_is_explicit_channel_checked_and_has_no_fallback():
    registry = OutreachProviderRegistry()
    provider = Provider()
    registry.register("resend", lambda: provider)
    assert registry.registered_provider_keys == ("resend",)
    assert registry.resolve("resend", "EMAIL") is provider
    with pytest.raises(OutreachError) as unknown:
        registry.resolve("unknown", "EMAIL")
    assert unknown.value.category == "UNKNOWN_PROVIDER"
    with pytest.raises(OutreachError):
        registry.resolve("resend", "SMS")
    with pytest.raises(OutreachError):
        registry.register("resend", lambda: provider)
