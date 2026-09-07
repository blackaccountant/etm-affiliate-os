"""Narrow operator-secret dependency for internal Pilot 1 launch actions."""

from secrets import compare_digest

from fastapi import Header, HTTPException

from app.core.config import settings


def require_operator_api_key(
    operator_key: str | None = Header(default=None, alias="X-ETM-Operator-Key"),
):
    configured = (settings.OPERATOR_API_KEY or "").strip()
    if not configured:
        raise HTTPException(status_code=503, detail="operator launch access is not configured")
    if operator_key is None or not compare_digest(operator_key, configured):
        raise HTTPException(status_code=401, detail="operator authorization required")
