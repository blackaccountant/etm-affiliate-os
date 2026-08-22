"""
Intelligence Fingerprint Service

Creates a stable fingerprint for the underlying
structured intelligence state.

The recommendation text is intentionally NOT included
because AI-generated wording can change even when the
actual intelligence state remains the same.
"""

from __future__ import annotations

import hashlib


def create_intelligence_fingerprint(
    score: int,
    grade: str,
    confidence: int,
) -> str:
    """
    Create a stable SHA-256 fingerprint for an
    intelligence evaluation.

    The fingerprint represents:

        score
        grade
        confidence

    Recommendation wording is deliberately excluded.
    """

    payload = (
        f"{int(score)}|"
        f"{str(grade).strip().upper()}|"
        f"{int(confidence)}"
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()