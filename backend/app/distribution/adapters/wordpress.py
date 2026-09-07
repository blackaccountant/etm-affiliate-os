"""Concrete WordPress REST API adapter for GLR2 publication."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.distribution.adapters.base import DistributionAdapter
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
)


def deterministic_wordpress_slug(distribution_run_id: str) -> str:
    digest = hashlib.sha256(distribution_run_id.strip().encode("utf-8")).hexdigest()[:18]
    return f"distribution-{digest}"


def _http_error_category(status_code: int | None) -> DistributionFailureCategory:
    if status_code == 401:
        return DistributionFailureCategory.AUTHENTICATION
    if status_code == 403:
        return DistributionFailureCategory.PERMISSION_DENIED
    if status_code in (400, 422):
        return DistributionFailureCategory.INVALID_CONTENT
    if status_code == 429:
        return DistributionFailureCategory.RATE_LIMIT
    return DistributionFailureCategory.UNKNOWN_PERMANENT


def _parse_wordpress_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


class WordPressDistributionAdapter(DistributionAdapter):
    @property
    def metadata(self) -> DistributionAdapterMetadata:
        return DistributionAdapterMetadata(
            platform="wordpress",
            supports_status_lookup=True,
            supports_native_idempotency=False,
        )

    def _base_url(self) -> str:
        base = (settings.CMS_WORDPRESS_BASE_URL or "").strip().rstrip("/")
        if not base:
            raise ValueError("CMS_WORDPRESS_BASE_URL is not configured")
        return base

    def _auth(self) -> tuple[str, str]:
        username = (settings.CMS_WORDPRESS_USERNAME or "").strip()
        app_password = (settings.CMS_WORDPRESS_APP_PASSWORD or "").strip()
        if not username or not app_password:
            raise ValueError("WordPress auth is not configured")
        return username, app_password

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None):
        base = self._base_url()
        url = f"{base}{path}"
        auth = self._auth()
        try:
            response = httpx.request(
                method,
                url,
                auth=auth,
                json=json_body,
                params=params,
                headers={"Accept": "application/json", "User-Agent": "ETM-WordPress-Adapter/1.0"},
                timeout=10.0,
            )
        except httpx.TimeoutException:
            raise TimeoutError("wordpress request timed out before the provider accepted the submission")
        except (httpx.NetworkError, httpx.RequestError):
            raise ConnectionError("wordpress provider is unavailable")
        return response

    def validate_target(self, request: DistributionValidationRequest) -> DistributionValidationResult:
        try:
            self._base_url()
            self._auth()
        except ValueError as exc:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.AUTHENTICATION,
                safe_message=str(exc),
            )

        try:
            response = self._request("GET", "/wp-json/wp/v2")
        except TimeoutError:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT,
                safe_message="wordpress site validation timed out",
            )
        except ConnectionError:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.PROVIDER_UNAVAILABLE,
                safe_message="wordpress site is unavailable",
            )

        if response.status_code == 200:
            return DistributionValidationResult(valid=True, safe_message="wordpress target is reachable")
        if response.status_code == 401:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.AUTHENTICATION,
                safe_message="wordpress authentication failed",
            )
        if response.status_code == 403:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.PERMISSION_DENIED,
                safe_message="wordpress permissions are insufficient",
            )
        if response.status_code == 429:
            return DistributionValidationResult(
                valid=False,
                failure_category=DistributionFailureCategory.RATE_LIMIT,
                safe_message="wordpress rate limit reached",
            )
        return DistributionValidationResult(
            valid=False,
            failure_category=DistributionFailureCategory.UNKNOWN_PERMANENT,
            safe_message="wordpress validation was not accepted",
        )

    def publish(self, request: DistributionPublishRequest) -> DistributionPublishResult:
        try:
            slug = deterministic_wordpress_slug(request.distribution_run_id)
            payload = {
                "content": request.content_body,
                "status": "publish",
                "slug": slug,
            }
            response = self._request("POST", "/wp-json/wp/v2/posts", json_body=payload)
        except ValueError as exc:
            return DistributionPublishResult(
                success=False,
                failure_category=DistributionFailureCategory.AUTHENTICATION,
                safe_message=str(exc),
            )
        except TimeoutError:
            return DistributionPublishResult(
                success=False,
                failure_category=DistributionFailureCategory.TIMEOUT_BEFORE_SUBMIT,
                safe_message="wordpress publish timed out before confirmation",
            )
        except ConnectionError:
            return DistributionPublishResult(
                success=False,
                failure_category=DistributionFailureCategory.PROVIDER_UNAVAILABLE,
                safe_message="wordpress provider is unavailable",
            )

        if response.status_code in (200, 201):
            try:
                data = response.json()
            except ValueError:
                return DistributionPublishResult(
                    success=False,
                    failure_category=DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT,
                    safe_message="wordpress publish response was not parseable",
                )
            post_id = data.get("id")
            link = data.get("link")
            published_at = _parse_wordpress_datetime(data.get("date_gmt") or data.get("date"))
            if not isinstance(post_id, (int, str)) or not link or published_at is None:
                return DistributionPublishResult(
                    success=False,
                    failure_category=DistributionFailureCategory.AMBIGUOUS_SUBMIT_RESULT,
                    safe_message="wordpress publish response was incomplete",
                )
            return DistributionPublishResult(
                success=True,
                external_post_id=str(post_id),
                external_url=str(link),
                published_at=published_at,
                safe_metadata={"platform_status": "published", "provider_state": "publish"},
            )

        status_code = response.status_code
        category = _http_error_category(status_code)
        safe_message = "wordpress publish was rejected"
        if status_code == 401:
            safe_message = "wordpress authentication failed"
        elif status_code == 403:
            safe_message = "wordpress permissions are insufficient"
        elif status_code in (400, 422):
            safe_message = "wordpress content or destination was invalid"
        elif status_code == 429:
            safe_message = "wordpress rate limit reached"
        elif status_code >= 500:
            safe_message = "wordpress provider returned a server error"
        return DistributionPublishResult(
            success=False,
            failure_category=category,
            safe_message=safe_message,
        )

    def get_publish_status(self, request: DistributionStatusRequest) -> DistributionStatusResult:
        if request.external_post_id:
            try:
                response = self._request("GET", f"/wp-json/wp/v2/posts/{request.external_post_id}")
            except TimeoutError:
                return DistributionStatusResult(
                    state=DistributionStatusLookupState.UNKNOWN,
                    safe_metadata={"platform_status": "timeout"},
                )
            except ConnectionError:
                return DistributionStatusResult(
                    state=DistributionStatusLookupState.UNKNOWN,
                    safe_metadata={"platform_status": "unavailable"},
                )
            if response.status_code == 404:
                return DistributionStatusResult(state=DistributionStatusLookupState.NOT_FOUND)
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
                if data.get("status") == "publish":
                    published_at = _parse_wordpress_datetime(data.get("date_gmt") or data.get("date"))
                    return DistributionStatusResult(
                        state=DistributionStatusLookupState.PUBLISHED,
                        external_post_id=str(data.get("id") or request.external_post_id),
                        external_url=str(data.get("link") or request.destination),
                        published_at=published_at,
                        safe_metadata={"platform_status": "published"},
                    )
                return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
            return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)

        slug = deterministic_wordpress_slug(request.distribution_run_id)
        try:
            response = self._request("GET", "/wp-json/wp/v2/posts", params={"slug": slug, "per_page": 10, "status": "publish"})
        except TimeoutError:
            return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
        except ConnectionError:
            return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
        if response.status_code == 404:
            return DistributionStatusResult(state=DistributionStatusLookupState.NOT_FOUND)
        if response.status_code == 200:
            try:
                posts = response.json()
            except ValueError:
                return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
            if not isinstance(posts, list) or not posts:
                return DistributionStatusResult(state=DistributionStatusLookupState.NOT_FOUND)
            post = posts[0]
            published_at = _parse_wordpress_datetime(post.get("date_gmt") or post.get("date"))
            return DistributionStatusResult(
                state=DistributionStatusLookupState.PUBLISHED,
                external_post_id=str(post.get("id") or ""),
                external_url=str(post.get("link") or ""),
                published_at=published_at,
                safe_metadata={"platform_status": "published"},
            )
        return DistributionStatusResult(state=DistributionStatusLookupState.UNKNOWN)
