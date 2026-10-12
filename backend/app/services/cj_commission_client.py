"""Read-only CJ Commission Detail GraphQL client for GLR3."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.core.config import settings


class CjCommissionClientError(RuntimeError):
    """Safe operational error that never includes CJ credentials."""


class CjCommissionClient:
    def __init__(
        self,
        *,
        publisher_cid: str | None = None,
        token: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.publisher_cid = (
            settings.CJ_PUBLISHER_CID if publisher_cid is None else publisher_cid
        ).strip()
        self._token = (
            settings.CJ_PERSONAL_ACCESS_TOKEN if token is None else token
        ).strip()
        self.endpoint = (
            settings.CJ_COMMISSIONS_API_URL if endpoint is None else endpoint
        ).strip()
        self.timeout_seconds = (
            settings.CJ_REQUEST_TIMEOUT_SECONDS
            if timeout_seconds is None
            else timeout_seconds
        )
        if not self.publisher_cid or not self.publisher_cid.isdigit():
            raise CjCommissionClientError("CJ publisher CID is not configured")
        if not self._token:
            raise CjCommissionClientError("CJ personal access token is not configured")
        if not self.endpoint.startswith("https://"):
            raise CjCommissionClientError("CJ commissions endpoint must use HTTPS")

    @staticmethod
    def _utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None:
            raise ValueError(f"{field} must be timezone-aware")
        return value.astimezone(timezone.utc)

    @classmethod
    def _validate_window(cls, since: datetime, before: datetime) -> tuple[datetime, datetime]:
        start = cls._utc(since, "since_posting_date")
        end = cls._utc(before, "before_posting_date")
        if end <= start:
            raise ValueError("CJ posting window must be positive")
        if (end - start).total_seconds() > 31 * 24 * 60 * 60:
            raise ValueError("CJ posting window cannot exceed 31 days")
        return start, end

    @staticmethod
    def _instant(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _query(self, since: datetime, before: datetime, cursor: str | None) -> str:
        args = [
            f"forPublishers: [{json.dumps(self.publisher_cid)}]",
            f"sincePostingDate: {json.dumps(self._instant(since))}",
            f"beforePostingDate: {json.dumps(self._instant(before))}",
        ]
        if cursor:
            args.append(f"sinceCommissionId: {json.dumps(cursor)}")
        return """
{
  publisherCommissions(%s) {
    count
    payloadComplete
    maxCommissionId
    records {
      commissionId
      publisherId
      advertiserId
      advertiserName
      actionStatus
      validationStatus
      actionType
      orderId
      original
      originalActionId
      postingDate
      eventDate
      saleAmountUsd
      pubCommissionAmountUsd
      websiteId
      websiteName
    }
  }
}
""" % ",\n    ".join(args)

    def fetch_commissions(
        self,
        *,
        since_posting_date: datetime,
        before_posting_date: datetime,
    ) -> list[dict]:
        since, before = self._validate_window(
            since_posting_date,
            before_posting_date,
        )
        records: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            try:
                response = httpx.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/graphql",
                    },
                    content=self._query(since, before, cursor),
                    timeout=self.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise CjCommissionClientError("CJ Commission Detail request failed") from exc

            if response.status_code != 200:
                raise CjCommissionClientError(
                    f"CJ Commission Detail returned HTTP {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise CjCommissionClientError(
                    "CJ Commission Detail returned invalid JSON"
                ) from exc
            if payload.get("errors"):
                raise CjCommissionClientError("CJ Commission Detail returned GraphQL errors")
            try:
                page = payload["data"]["publisherCommissions"]
                page_records = page["records"]
                complete = page["payloadComplete"]
            except (KeyError, TypeError) as exc:
                raise CjCommissionClientError(
                    "CJ Commission Detail response shape is invalid"
                ) from exc
            if not isinstance(page_records, list) or not isinstance(complete, bool):
                raise CjCommissionClientError(
                    "CJ Commission Detail response types are invalid"
                )
            records.extend(page_records)
            if complete:
                return records

            next_cursor = str(page.get("maxCommissionId") or "").strip()
            if not next_cursor or next_cursor in seen_cursors:
                raise CjCommissionClientError(
                    "CJ Commission Detail pagination cursor is invalid"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
