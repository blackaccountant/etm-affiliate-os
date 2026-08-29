"""Phase 5C provider-neutral distribution adapter boundary tests."""

from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

import pytest

from app.distribution.adapters.base import DistributionAdapter
from app.distribution.adapters.registry import DistributionAdapterRegistry
from app.distribution.contracts import (
    DistributionAdapterMetadata,
    DistributionFailureCategory,
    DistributionPublishRequest,
    DistributionPublishResult,
    DistributionStatusLookupState,
    DistributionStatusRequest,
    DistributionStatusResult,
    DistributionValidationRequest,
    DistributionValidationResult,
    distribution_correlation_key,
)
from app.distribution.exceptions import DuplicateDistributionAdapterError, UnsupportedDistributionPlatformError
from app.distribution.failure_adapter import DistributionFailureAdapter
from app.retry.failure_classifier import FailureClassifier


def digest(value: str = "payload") -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validation_request(**changes) -> DistributionValidationRequest:
    values = {
        "distribution_run_id": " run-1 ",
        "platform": " Fake   Platform ",
        "account_reference": " primary-account ",
        "destination": " channel/main ",
        "content_type": " ARTICLE ",
        "payload_fingerprint": digest(),
    }
    values.update(changes)
    return DistributionValidationRequest(**values)


def publish_request(**changes) -> DistributionPublishRequest:
    values = {
        "distribution_run_id": "run-1",
        "generated_content_artifact_id": "artifact-1",
        "content_evaluation_id": "evaluation-1",
        "platform": "Fake Platform",
        "account_reference": "primary-account",
        "destination": "channel/main",
        "payload_fingerprint": digest(),
        "content_body": "Already prepared content.",
        "scheduled_for": datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
    }
    values.update(changes)
    return DistributionPublishRequest(**values)


def status_request(**changes) -> DistributionStatusRequest:
    values = {
        "distribution_run_id": "run-1",
        "platform": "Fake Platform",
        "account_reference": "primary-account",
        "destination": "channel/main",
    }
    values.update(changes)
    return DistributionStatusRequest(**values)


class FakeDistributionAdapter(DistributionAdapter):
    """Programmable deterministic adapter used only by the Phase 5C unit suite."""

    def __init__(self, *, platform: str = "Fake Platform", validation: str = "VALID", publish: str | DistributionFailureCategory = "SUCCESS", status: DistributionStatusLookupState = DistributionStatusLookupState.PUBLISHED, supports_status_lookup: bool = True, supports_native_idempotency: bool = True):
        self._metadata = DistributionAdapterMetadata(platform, supports_status_lookup, supports_native_idempotency)
        self.validation_outcome = validation
        self.publish_outcome = publish
        self.status_outcome = status
        self.validation_calls = 0
        self.publish_calls = 0
        self.status_calls = 0

    @property
    def metadata(self) -> DistributionAdapterMetadata:
        return self._metadata

    def validate_target(self, request: DistributionValidationRequest) -> DistributionValidationResult:
        self.validation_calls += 1
        if self.validation_outcome == "INVALID_TARGET":
            return DistributionValidationResult(False, "destination is not valid", DistributionFailureCategory.INVALID_DESTINATION)
        return DistributionValidationResult(True, "target accepted", normalized_destination=request.destination)

    def publish(self, request: DistributionPublishRequest) -> DistributionPublishResult:
        self.publish_calls += 1
        if self.publish_outcome != "SUCCESS":
            return DistributionPublishResult(False, failure_category=self.publish_outcome, safe_message="safe fake adapter failure", provider_correlation_id=request.correlation_key)
        return DistributionPublishResult(
            True,
            external_post_id="fake-post-1",
            external_url="https://fake.invalid/posts/1",
            published_at=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
            safe_metadata={"platform_status": "published", "attempt": 1},
            provider_idempotency_key=request.correlation_key,
            provider_correlation_id=request.correlation_key,
        )

    def get_publish_status(self, request: DistributionStatusRequest) -> DistributionStatusResult:
        self.status_calls += 1
        if not self.metadata.supports_status_lookup:
            return super().get_publish_status(request)
        if self.status_outcome is DistributionStatusLookupState.PUBLISHED:
            return DistributionStatusResult(
                self.status_outcome,
                external_post_id="fake-post-1",
                external_url="https://fake.invalid/posts/1",
                published_at=datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc),
                safe_metadata={"platform_status": "published"},
            )
        return DistributionStatusResult(self.status_outcome, safe_metadata={"platform_status": self.status_outcome.value.lower()})


@pytest.fixture(autouse=True)
def no_configured_database_or_network(monkeypatch):
    """Fail closed if a pure adapter test reaches configured infrastructure."""
    import app.database.session as database_session

    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("configured DB or network")
        raise AssertionError("Phase 5C adapter tests must not use configured DB, network, or providers")

    class ForbiddenEngine:
        def connect(self, *args, **kwargs):
            forbidden(*args, **kwargs)

        def begin(self, *args, **kwargs):
            forbidden(*args, **kwargs)

    monkeypatch.setattr(database_session, "SessionLocal", forbidden)
    monkeypatch.setattr(database_session, "engine", ForbiddenEngine())
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    yield
    assert calls == []


def test_register_resolve_and_normalize_platform_with_capabilities():
    adapter = FakeDistributionAdapter()
    registry = DistributionAdapterRegistry()
    registry.register(adapter)
    assert registry.resolve("  FAKE   PLATFORM ") is adapter
    assert registry.registered_platforms == ("fake platform",)
    assert adapter.metadata.to_dict() == {
        "platform": "fake platform",
        "supports_status_lookup": True,
        "supports_native_idempotency": True,
    }


def test_duplicate_registration_fails_without_replacing_original_adapter():
    registry = DistributionAdapterRegistry()
    original = FakeDistributionAdapter()
    registry.register(original)
    with pytest.raises(DuplicateDistributionAdapterError, match="already registered"):
        registry.register(FakeDistributionAdapter(platform="FAKE PLATFORM"))
    assert registry.resolve("fake platform") is original


def test_unsupported_platform_has_stable_category():
    with pytest.raises(UnsupportedDistributionPlatformError) as error:
        DistributionAdapterRegistry().resolve("missing platform")
    assert error.value.category is DistributionFailureCategory.UNSUPPORTED_PLATFORM
    assert error.value.platform == "missing platform"


def test_fake_validation_outcomes_are_normalized_and_counted():
    valid = FakeDistributionAdapter()
    invalid = FakeDistributionAdapter(validation="INVALID_TARGET")
    accepted = valid.validate_target(validation_request())
    rejected = invalid.validate_target(validation_request(destination="bad target"))
    assert accepted.valid is True and accepted.normalized_destination == "channel/main"
    assert rejected.to_dict() == {
        "valid": False,
        "safe_message": "destination is not valid",
        "failure_category": "INVALID_DESTINATION",
        "normalized_destination": None,
    }
    assert (valid.validation_calls, invalid.validation_calls) == (1, 1)


def test_publish_success_is_utc_json_safe_and_uses_stable_correlation():
    adapter = FakeDistributionAdapter()
    request = publish_request()
    result = adapter.publish(request)
    assert request.correlation_key == distribution_correlation_key("run-1") == "distribution:run-1"
    assert result.success is True and result.published_at.tzinfo == timezone.utc
    assert result.external_post_id == "fake-post-1" and result.external_url == "https://fake.invalid/posts/1"
    assert json.loads(json.dumps(request.to_dict()))["scheduled_for"].endswith("+00:00")
    assert json.loads(json.dumps(result.to_dict()))["safe_metadata"] == {"platform_status": "published", "attempt": 1}
    assert adapter.publish_calls == 1


@pytest.mark.parametrize(
    ("category", "expected_text", "retryable"),
    [
        (DistributionFailureCategory.RATE_LIMIT, "rate limit", True),
        (DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT, "timeout before submit", True),
        (DistributionFailureCategory.PROVIDER_UNAVAILABLE, "upstream unavailable", True),
        (DistributionFailureCategory.AUTHENTICATION, "authentication error", False),
        (DistributionFailureCategory.PERMISSION_DENIED, "permission denied", False),
        (DistributionFailureCategory.INVALID_CONTENT, "validation error: invalid content", False),
        (DistributionFailureCategory.INVALID_DESTINATION, "validation error: invalid destination", False),
        (DistributionFailureCategory.UNSUPPORTED_PLATFORM, "unsupported distribution platform", False),
        (DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT, "external publish result requires reconciliation", False),
        (DistributionFailureCategory.UNKNOWN_PERMANENT, "permanent distribution provider error", False),
    ],
)
def test_publish_failures_preserve_category_and_map_to_safe_classifier_text(category, expected_text, retryable):
    adapter = FakeDistributionAdapter(publish=category)
    result = adapter.publish(publish_request())
    text = DistributionFailureAdapter.to_classifier_text(result.failure_category)
    assert result.success is False and result.failure_category is category
    assert text == expected_text
    assert FailureClassifier().classify(text)["retryable"] is retryable
    assert category.retryable is retryable


def test_ambiguous_result_is_distinct_from_timeout_and_never_blind_retryable():
    ambiguous = DistributionFailureAdapter.to_classifier_text(DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT)
    timeout = DistributionFailureAdapter.to_classifier_text(DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT)
    assert ambiguous != timeout
    assert FailureClassifier().classify(ambiguous)["retryable"] is False
    assert DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT.retryable is False


@pytest.mark.parametrize("state", list(DistributionStatusLookupState))
def test_status_lookup_normalizes_each_reconciliation_state_and_counts_calls(state):
    adapter = FakeDistributionAdapter(status=state)
    result = adapter.get_publish_status(status_request())
    assert result.state is state and adapter.status_calls == 1
    if state is DistributionStatusLookupState.PUBLISHED:
        assert result.external_post_id == "fake-post-1" and result.published_at.tzinfo == timezone.utc
    else:
        assert result.external_post_id is None and result.external_url is None
    json.dumps(result.to_dict())


def test_adapter_without_status_capability_rejects_status_lookup_without_side_effects():
    adapter = FakeDistributionAdapter(supports_status_lookup=False)
    with pytest.raises(NotImplementedError, match="does not support status lookup"):
        adapter.get_publish_status(status_request())
    assert adapter.status_calls == 1


def test_request_contracts_reject_malformed_values_and_naive_datetimes():
    with pytest.raises(ValueError, match="platform is required"):
        validation_request(platform=" \t ")
    with pytest.raises(ValueError, match="account_reference is required"):
        publish_request(account_reference="")
    with pytest.raises(ValueError, match="destination must be text"):
        status_request(destination=object())
    with pytest.raises(ValueError, match="SHA-256"):
        publish_request(payload_fingerprint="not-a-fingerprint")
    with pytest.raises(ValueError, match="timezone-aware"):
        publish_request(scheduled_for=datetime(2026, 8, 29, 10, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        DistributionPublishResult(True, "post", "https://fake.invalid/post", datetime(2026, 8, 29, 10, 0))
    with pytest.raises(ValueError, match="unsupported keys"):
        DistributionPublishResult(True, "post", "https://fake.invalid/post", datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc), safe_metadata={"raw_response": "forbidden"})


def test_public_request_contracts_have_no_secret_fields_and_all_contracts_serialize():
    secret_names = {"password", "token", "access_token", "refresh_token", "api_key", "secret", "cookie"}
    request_types = (DistributionValidationRequest, DistributionPublishRequest, DistributionStatusRequest)
    assert all(secret_names.isdisjoint({field.name for field in fields(contract)}) for contract in request_types)
    payloads = [
        validation_request().to_dict(),
        DistributionValidationResult(True, "accepted", normalized_destination="channel/main").to_dict(),
        publish_request().to_dict(),
        FakeDistributionAdapter().publish(publish_request()).to_dict(),
        status_request().to_dict(),
        FakeDistributionAdapter().get_publish_status(status_request()).to_dict(),
    ]
    for payload in payloads:
        assert json.loads(json.dumps(payload)) == payload


def test_phase_5c_modules_do_not_add_mission_workflow_or_distribution_lifecycle_writes():
    distribution_root = Path(__file__).parents[1] / "app" / "distribution"
    phase_5c_paths = [
        distribution_root / "contracts.py",
        distribution_root / "exceptions.py",
        distribution_root / "failure_adapter.py",
        *(distribution_root / "adapters").rglob("*.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in phase_5c_paths)
    forbidden = ("MissionManager", "ContentDistributionMission", "distribution_publish", "SessionLocal", ".commit(", ".flush(", "httpx", "requests")
    assert all(token not in source for token in forbidden)
