"""Process-local opaque browser sessions for the single operator console.

THIS REGISTRY IS PROCESS-LOCAL. MULTI-WORKER PRODUCTION DEPLOYMENT REQUIRES
A SHARED SESSION STORE.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperatorSession:
    authority: str
    expires_at: datetime
    # Retained only in process memory so GET /operator/session can restore the
    # browser's in-memory CSRF value after a tab reload.
    csrf_token: str


class OperatorSessionRegistry:
    """A lock-protected, in-memory registry for one application process."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, OperatorSession] = {}
        self._lock = threading.RLock()

    def create(self, ttl_seconds: int) -> tuple[str, str, OperatorSession]:
        session_token = secrets.token_urlsafe(32)  # at least 256 bits of entropy
        csrf_token = secrets.token_urlsafe(32)
        record = OperatorSession(
            authority="OPERATOR",
            expires_at=self._clock() + timedelta(seconds=ttl_seconds),
            csrf_token=csrf_token,
        )
        with self._lock:
            self._purge_expired_locked()
            self._sessions[_digest(session_token)] = record
        return session_token, csrf_token, record

    def validate(self, session_token: str | None) -> OperatorSession | None:
        if not session_token:
            return None
        with self._lock:
            self._purge_expired_locked()
            return self._sessions.get(_digest(session_token))

    def validate_csrf(self, session_token: str | None, csrf_token: str | None) -> bool:
        if not session_token or not csrf_token:
            return False
        record = self.validate(session_token)
        return bool(record and hmac.compare_digest(record.csrf_token, csrf_token))

    def revoke(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._lock:
            self._sessions.pop(_digest(session_token), None)

    def clear(self) -> None:
        """Test-safe process-local reset; never persists anything."""
        with self._lock:
            self._sessions.clear()

    def _purge_expired_locked(self) -> None:
        now = self._clock()
        for token_digest, record in tuple(self._sessions.items()):
            if record.expires_at <= now:
                self._sessions.pop(token_digest, None)


operator_session_registry = OperatorSessionRegistry()
