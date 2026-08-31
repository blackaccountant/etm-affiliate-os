"""Injected-transport Resend adapter proofs; the suite never opens a network socket."""

import httpx
import pytest

from app.outreach.provider_contracts import EphemeralRecipient, ProviderFailureCategory, ProviderSendOutcome, ProviderSendRequest
from app.outreach.providers.resend import ResendEmailProvider


def request(operation="operation"):
    return ProviderSendRequest(
        operation, "ETM <sender@example.com>", EphemeralRecipient("EMAIL", "recipient@example.com"),
        "Subject", "Secret body", "TEXT",
    )


def provider(handler, **kwargs):
    timeout_seconds = kwargs.pop("timeout_seconds", 5)
    return ResendEmailProvider(
        api_key="test-secret", from_email="sender@example.com", from_name="ETM",
        timeout_seconds=timeout_seconds, transport=httpx.MockTransport(handler), **kwargs,
    )


def test_acceptance_uses_bearer_and_idempotency_and_returns_only_opaque_reference():
    captured = {}
    def handler(http_request):
        captured["authorization"] = http_request.headers["Authorization"]
        captured["idempotency"] = http_request.headers["Idempotency-Key"]
        return httpx.Response(200, json={"id": "opaque-email-id", "ignored": {"raw": "response"}})
    result = provider(handler).send(request())
    assert result.outcome is ProviderSendOutcome.DEFINITELY_ACCEPTED
    assert result.provider_reference == "opaque-email-id" and not hasattr(result, "raw_response")
    assert captured == {"authorization": "Bearer test-secret", "idempotency": "operation"}
    assert "test-secret" not in repr(result) and "recipient@example.com" not in repr(result)


@pytest.mark.parametrize("status,category,outcome", [
    (400, ProviderFailureCategory.DETERMINISTIC_REJECTION, ProviderSendOutcome.DEFINITELY_REJECTED),
    (401, ProviderFailureCategory.CONFIGURATION_AUTHENTICATION, None),
    (409, ProviderFailureCategory.IDEMPOTENCY_CONFLICT, None),
    (429, ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, None),
    (503, ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, ProviderSendOutcome.AMBIGUOUS),
])
def test_http_failures_are_bounded_and_classified(status, category, outcome):
    result = provider(lambda _request: httpx.Response(status, json={"message": "must not leak"})).send(request())
    assert result.failure.category is category and result.outcome is outcome
    assert "must not leak" not in repr(result)


def test_connect_failure_is_definitely_before_side_effect_but_read_timeout_is_ambiguous():
    def connect_failure(http_request):
        raise httpx.ConnectError("recipient@example.com Secret body", request=http_request)
    before = provider(connect_failure).send(request())
    assert before.outcome is None
    assert before.failure.category is ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT
    assert "recipient@example.com" not in repr(before)

    def read_timeout(http_request):
        raise httpx.ReadTimeout("recipient@example.com Secret body", request=http_request)
    ambiguous = provider(read_timeout).send(request())
    assert ambiguous.outcome is ProviderSendOutcome.AMBIGUOUS
    assert ambiguous.failure.category is ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT


def test_missing_api_key_requires_no_network_and_is_non_retryable():
    calls = []
    adapter = ResendEmailProvider(
        api_key="", from_email="sender@example.com",
        transport=httpx.MockTransport(lambda _request: calls.append(True)),
    )
    result = adapter.send(request())
    assert calls == [] and result.outcome is None
    assert result.failure.category is ProviderFailureCategory.CONFIGURATION_AUTHENTICATION


def test_timeout_is_strictly_bounded_and_email_only():
    adapter = provider(lambda _request: httpx.Response(200, json={"id": "id"}), timeout_seconds=999)
    assert adapter._timeout_seconds == 30.0 and adapter.capabilities.channels == ("EMAIL",)
