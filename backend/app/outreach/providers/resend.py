"""Resend EMAIL adapter with an injectable, network-free test boundary."""

from __future__ import annotations

from datetime import timedelta

import httpx

from app.core.config import settings
from app.outreach.contracts import OutreachError
from app.outreach.provider_contracts import (
    ProviderCapabilities,
    ProviderFailureCategory,
    ProviderSendOutcome,
    ProviderSendRequest,
    ProviderSendResult,
    RESEND_CONTRACT_VERSION,
    RESEND_DOCUMENTED_IDEMPOTENCY_HOURS,
    RESEND_PROVIDER_KEY,
    RESEND_SAFE_REPLAY_HOURS,
)
from app.outreach.provider_failure_adapter import ProviderFailureAdapter


class ResendEmailProvider:
    endpoint = "https://api.resend.com/emails"

    def __init__(self, *, api_key: str | None = None, from_email: str | None = None,
                 from_name: str | None = None, timeout_seconds: float | None = None,
                 client: httpx.Client | None = None, transport: httpx.BaseTransport | None = None):
        self._api_key = settings.RESEND_API_KEY if api_key is None else api_key
        self._from_email = settings.RESEND_FROM_EMAIL if from_email is None else from_email
        self._from_name = settings.RESEND_FROM_NAME if from_name is None else from_name
        configured_timeout = settings.RESEND_REQUEST_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        self._timeout_seconds = max(0.1, min(float(configured_timeout), 30.0))
        self._client = client
        self._transport = transport

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            RESEND_PROVIDER_KEY, RESEND_CONTRACT_VERSION, ("EMAIL",), True,
            timedelta(hours=RESEND_DOCUMENTED_IDEMPOTENCY_HOURS),
            timedelta(hours=RESEND_SAFE_REPLAY_HOURS), True,
        )

    @property
    def sender_identity(self) -> str:
        email = (self._from_email or "").strip()
        if not email:
            raise OutreachError("PROVIDER_CONFIGURATION", "Resend sender is not configured")
        name = (self._from_name or "").strip()
        return f"{name} <{email}>" if name else email

    def send(self, request: ProviderSendRequest) -> ProviderSendResult:
        if request.recipient.channel != "EMAIL":
            raise OutreachError("UNSUPPORTED_CHANNEL", "Resend M9C1 supports EMAIL only")
        if not (self._api_key or "").strip():
            failure = ProviderFailureAdapter.from_status(401)
            return ProviderSendResult(None, failure=failure)
        payload = {
            "from": request.sender,
            "to": [request.recipient.value],
            "subject": request.subject or "",
            "text" if request.content_format == "TEXT" else "html": request.body,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": request.operation_key,
            "Content-Type": "application/json",
        }
        owns_client = self._client is None
        client = self._client or httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout_seconds),
        )
        try:
            try:
                response = client.post(self.endpoint, headers=headers, json=payload)
            except Exception as error:
                failure = ProviderFailureAdapter.from_exception(error)
                outcome = (
                    ProviderSendOutcome.AMBIGUOUS
                    if failure.category is ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT else None
                )
                return ProviderSendResult(outcome, failure=failure)
            if 200 <= response.status_code < 300:
                try:
                    reference = response.json().get("id")
                except (ValueError, AttributeError):
                    reference = None
                if not isinstance(reference, str) or not reference.strip() or len(reference.strip()) > 255:
                    failure = ProviderFailureAdapter.from_exception(RuntimeError("invalid response"))
                    return ProviderSendResult(ProviderSendOutcome.AMBIGUOUS, failure=failure)
                return ProviderSendResult(ProviderSendOutcome.DEFINITELY_ACCEPTED, reference.strip())
            failure = ProviderFailureAdapter.from_status(response.status_code)
            if failure.category is ProviderFailureCategory.DETERMINISTIC_REJECTION:
                return ProviderSendResult(ProviderSendOutcome.DEFINITELY_REJECTED, failure=failure)
            if failure.category is ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT:
                return ProviderSendResult(ProviderSendOutcome.AMBIGUOUS, failure=failure)
            return ProviderSendResult(None, failure=failure)
        finally:
            if owns_client:
                client.close()
