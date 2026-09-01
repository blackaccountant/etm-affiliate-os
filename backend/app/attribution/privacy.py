"""Structural privacy boundary for persisted attribution source identities.

M10A2 accepts only a conservative source-system slug and an already-canonical
digest.  The future bridge owns digest derivation from an authorized, non-PII
event identity; hashing unnecessary sensitive input is not authorized here.
"""

from __future__ import annotations

from app.attribution.contracts import source_identity


def validate_privacy_safe_source(
    source_namespace: str, source_event_key_digest: str,
) -> tuple[str, str]:
    """Validate and return the only source identity M10A2 may persist."""

    return source_identity(source_namespace, source_event_key_digest)
