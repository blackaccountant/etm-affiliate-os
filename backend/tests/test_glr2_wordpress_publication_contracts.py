from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.distribution import PilotCmsPublishPayload, _absolute_tracked_url, _render_final_content
from app.core.config import settings
from app.distribution.adapters.wordpress import WordPressDistributionAdapter, deterministic_wordpress_slug
from app.distribution.contracts import (
    DistributionFailureCategory,
    DistributionStatusLookupState,
    DistributionValidationResult,
)


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_wordpress_adapter_metadata():
    metadata = WordPressDistributionAdapter().metadata
    assert metadata.platform == "wordpress"
    assert metadata.supports_status_lookup is True
    assert metadata.supports_native_idempotency is False


def test_publish_uses_content_status_and_deterministic_slug(monkeypatch):
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["auth"] = kwargs.get("auth")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(201, {"id": 432, "link": "https://example.com/hello", "date_gmt": "2026-09-07T12:00:00Z"})

    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_BASE_URL", "https://example.com")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_USERNAME", "etm-user")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_APP_PASSWORD", "secret")
    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", fake_request)

    result = WordPressDistributionAdapter().publish(
        SimpleNamespace(
            distribution_run_id="run-123",
            content_body="<p>Hello</p>",
            payload_fingerprint="a" * 64,
            destination="blog",
            correlation_key="distribution:run-123",
            scheduled_for=None,
        )
    )

    assert result.success is True
    assert captured["method"] == "POST"
    assert captured["json"]["content"] == "<p>Hello</p>"
    assert "content.rendered" not in captured["json"]
    assert captured["json"]["status"] == "publish"
    assert captured["json"]["slug"] == deterministic_wordpress_slug("run-123")
    assert result.external_post_id == "432"
    assert result.external_url == "https://example.com/hello"
    assert result.published_at == datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def test_deterministic_slug_is_stable_and_unique_by_run():
    first = deterministic_wordpress_slug("distribution-run-1")
    second = deterministic_wordpress_slug("distribution-run-1")
    third = deterministic_wordpress_slug("distribution-run-2")
    assert first == second
    assert first != third


def test_validation_and_failure_classification(monkeypatch):
    adapter = WordPressDistributionAdapter()
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_BASE_URL", "https://example.com")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_USERNAME", "etm-user")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_APP_PASSWORD", "secret")

    def fake_request(method, url, **kwargs):
        if method == "GET":
            return _FakeResponse(401)
        raise AssertionError("unexpected call")

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", fake_request)
    result = adapter.validate_target(SimpleNamespace(distribution_run_id="run", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64))
    assert result.valid is False
    assert result.failure_category == DistributionFailureCategory.AUTHENTICATION

    def auth_fail(method, url, **kwargs):
        return _FakeResponse(403)

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", auth_fail)
    result = adapter.validate_target(SimpleNamespace(distribution_run_id="run", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64))
    assert result.failure_category == DistributionFailureCategory.PERMISSION_DENIED

    def rate_fail(method, url, **kwargs):
        return _FakeResponse(429)

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", rate_fail)
    result = adapter.validate_target(SimpleNamespace(distribution_run_id="run", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64))
    assert result.failure_category == DistributionFailureCategory.RATE_LIMIT

    def timeout_event(method, url, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", timeout_event)
    result = adapter.validate_target(SimpleNamespace(distribution_run_id="run", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64))
    assert result.failure_category == DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT


def test_publish_error_classification(monkeypatch):
    adapter = WordPressDistributionAdapter()
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_BASE_URL", "https://example.com")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_USERNAME", "etm-user")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_APP_PASSWORD", "secret")

    def reject(method, url, **kwargs):
        return _FakeResponse(422)

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", reject)
    result = adapter.publish(SimpleNamespace(distribution_run_id="r1", content_body="body", payload_fingerprint="a" * 64, destination="blog", scheduled_for=None, correlation_key="distribution:r1", generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform="wordpress", account_reference="acct"))
    assert result.success is False
    assert result.failure_category == DistributionFailureCategory.INVALID_CONTENT

    def network(method, url, **kwargs):
        raise ConnectionError()

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", network)
    result = adapter.publish(SimpleNamespace(distribution_run_id="r1", content_body="body", payload_fingerprint="a" * 64, destination="blog", scheduled_for=None, correlation_key="distribution:r1", generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform="wordpress", account_reference="acct"))
    assert result.failure_category == DistributionFailureCategory.PROVIDER_UNAVAILABLE


def test_status_lookup_by_id_and_slug(monkeypatch):
    adapter = WordPressDistributionAdapter()
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_BASE_URL", "https://example.com")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_USERNAME", "etm-user")
    monkeypatch.setattr("app.distribution.adapters.wordpress.settings.CMS_WORDPRESS_APP_PASSWORD", "secret")

    def fake_request(method, url, **kwargs):
        if method == "GET" and url.endswith("posts/99"):
            return _FakeResponse(200, {"id": 99, "link": "https://example.com/post-99", "status": "publish", "date_gmt": "2026-09-07T12:00:00Z"})
        if method == "GET" and url.endswith("posts") and kwargs.get("params", {}).get("slug") == deterministic_wordpress_slug("run-5"):
            return _FakeResponse(200, [{"id": 88, "link": "https://example.com/post-88", "status": "publish", "date_gmt": "2026-09-07T12:00:00Z"}])
        if method == "GET" and url.endswith("posts"):
            return _FakeResponse(200, [])
        raise AssertionError(url)

    monkeypatch.setattr("app.distribution.adapters.wordpress.httpx.request", fake_request)
    result = adapter.get_publish_status(SimpleNamespace(distribution_run_id="run-3", platform="wordpress", account_reference="acct", destination="blog", external_post_id="99", correlation_key="distribution:run-3"))
    assert result.state == DistributionStatusLookupState.PUBLISHED
    assert result.external_post_id == "99"
    assert result.external_url == "https://example.com/post-99"

    slug_result = adapter.get_publish_status(SimpleNamespace(distribution_run_id="run-5", platform="wordpress", account_reference="acct", destination="blog", external_post_id=None, correlation_key="distribution:run-5"))
    assert slug_result.state == DistributionStatusLookupState.PUBLISHED
    assert slug_result.external_post_id == "88"

    no_match = adapter.get_publish_status(SimpleNamespace(distribution_run_id="run-6", platform="wordpress", account_reference="acct", destination="blog", external_post_id=None, correlation_key="distribution:run-6"))
    assert no_match.state == DistributionStatusLookupState.NOT_FOUND


def test_operator_api_payload_and_extra_rejection():
    payload = PilotCmsPublishPayload(distribution_run_id="run-1")
    assert payload.distribution_run_id == "run-1"
    with pytest.raises(ValidationError):
        PilotCmsPublishPayload(distribution_run_id="run-1", platform="wordpress")
    with pytest.raises(ValidationError):
        PilotCmsPublishPayload(distribution_run_id="run-1", tracking_code="abc")


def test_absolute_tracked_url_and_final_render_are_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://api.example.com/ ")
    assert _absolute_tracked_url("abc123") == "https://api.example.com/affiliate-links/go/abc123"
    rendered = _render_final_content("<p>hello</p>", "https://api.example.com/affiliate-links/go/abc123")
    assert "https://api.example.com/affiliate-links/go/abc123" in rendered
    assert rendered == _render_final_content("<p>hello</p>", "https://api.example.com/affiliate-links/go/abc123")


def test_pilot_cms_publish_replay_returns_existing_receipt(monkeypatch):
    calls = {"count": 0}

    class FakeDb:
        def __init__(self):
            self.run = SimpleNamespace(id="run-7", status="COMPLETED", external_post_id="12", external_url="https://example.com/post-12", generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64, prepared_content_body="body", scheduled_for=None)
        def get(self, cls, key):
            if cls.__name__ == "DistributionRun":
                return self.run
            return None
        def query(self, *args, **kwargs):
            class Query:
                def filter_by(self, **_):
                    return self
                def first(self):
                    return SimpleNamespace(id="publication", attribution_publication_id="pub", attribution_context_id="ctx", tracking_code="abc123")
            return Query()
        def commit(self):
            return None

    class FakeAdapter:
        def publish(self, request):
            calls["count"] += 1
            raise AssertionError("publish must not be called for completed replay")

    monkeypatch.setattr("app.api.distribution.WordPressDistributionAdapter", FakeAdapter)
    db = FakeDb()
    result = __import__("app.api.distribution", fromlist=["pilot_cms_publish"]).pilot_cms_publish(SimpleNamespace(distribution_run_id="run-7"), db)
    assert result["external_post_id"] == "12"
    assert result["external_url"] == "https://example.com/post-12"
    assert calls["count"] == 0


def test_no_affiliate_create_or_context_mutation_on_route(monkeypatch):
    seen = {"calls": 0}

    class FakeDb:
        def __init__(self):
            self.run = SimpleNamespace(id="run-8", status="CREATED", generated_content_artifact_id="artifact", content_evaluation_id="evaluation", platform="wordpress", account_reference="acct", destination="blog", payload_fingerprint="a" * 64, prepared_content_body="body", scheduled_for=None)
        def get(self, cls, key):
            if cls.__name__ == "DistributionRun":
                return self.run
            return None
        def query(self, *args, **kwargs):
            seen["calls"] += 1
            class Query:
                def filter_by(self, **_):
                    return self
                def first(self):
                    return SimpleNamespace(id="publication", attribution_publication_id="pub", attribution_context_id="ctx", tracking_code="track-8")
            return Query()
        def commit(self):
            return None

    class FakeAdapter:
        def publish(self, request):
            return SimpleNamespace(success=True, external_post_id="9", external_url="https://example.com/published", published_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc), safe_metadata={"platform_status": "published"}, failure_category=None, safe_message=None)

    monkeypatch.setattr("app.api.distribution.WordPressDistributionAdapter", FakeAdapter)
    monkeypatch.setattr("app.api.distribution._absolute_tracked_url", lambda tracking_code: "https://api.example.com/affiliate-links/go/track-8")
    result = __import__("app.api.distribution", fromlist=["pilot_cms_publish"]).pilot_cms_publish(SimpleNamespace(distribution_run_id="run-8"), FakeDb())
    assert result["external_post_id"] == "9"
    assert seen["calls"] >= 1
