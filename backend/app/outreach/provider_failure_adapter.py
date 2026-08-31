"""Safe provider-failure mapping; raw exceptions never leave this boundary."""

from __future__ import annotations

import httpx

from app.outreach.provider_contracts import ProviderFailure, ProviderFailureCategory


class ProviderFailureAdapter:
    @staticmethod
    def from_exception(error: Exception) -> ProviderFailure:
        if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
            return ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "PROVIDER_UNREACHABLE")
        if isinstance(error, (httpx.ReadTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
            return ProviderFailure(ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, "PROVIDER_RESULT_AMBIGUOUS")
        return ProviderFailure(ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, "PROVIDER_RESULT_AMBIGUOUS")

    @staticmethod
    def from_status(status_code: int) -> ProviderFailure:
        if status_code in {401, 403}:
            return ProviderFailure(ProviderFailureCategory.CONFIGURATION_AUTHENTICATION, "PROVIDER_AUTHENTICATION_FAILED")
        if status_code == 429:
            return ProviderFailure(ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT, "PROVIDER_RATE_LIMITED")
        if status_code in {409, 422}:
            return ProviderFailure(ProviderFailureCategory.IDEMPOTENCY_CONFLICT, "PROVIDER_IDEMPOTENCY_CONFLICT")
        if 400 <= status_code < 500:
            return ProviderFailure(ProviderFailureCategory.DETERMINISTIC_REJECTION, "PROVIDER_REJECTED_REQUEST")
        return ProviderFailure(ProviderFailureCategory.AMBIGUOUS_SIDE_EFFECT, "PROVIDER_RESULT_AMBIGUOUS")

    @staticmethod
    def classifier_text(failure: ProviderFailure) -> str:
        if failure.category is ProviderFailureCategory.TRANSIENT_BEFORE_SIDE_EFFECT:
            return "temporarily unavailable"
        if failure.category is ProviderFailureCategory.CONFIGURATION_AUTHENTICATION:
            return "authentication error"
        if failure.category is ProviderFailureCategory.IDEMPOTENCY_CONFLICT:
            return "provider idempotency conflict"
        if failure.category is ProviderFailureCategory.DETERMINISTIC_REJECTION:
            return "provider rejected request"
        return "provider result requires reconciliation"
