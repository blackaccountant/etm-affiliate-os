"""Deterministic canonical identity and run-scoped deduplication helpers."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit


def canonical_domain(value: str | None) -> str:
    """Return the stable company domain; malformed or empty input returns an empty string."""
    if not value:
        return ""
    raw = str(value).strip().lower()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    hostname = parsed.hostname
    if not hostname:
        return ""
    hostname = hostname.rstrip(".")
    if not hostname or any(character.isspace() for character in hostname):
        return ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _normalized_part(value: str | None, fallback: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip().lower())
    return text or fallback


def _digest(*parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def program_identity_key(
    domain: str | None,
    affiliate_network: str | None = None,
    program_name: str | None = None,
) -> str:
    """Stable program identity; missing network/program uses the explicit ``direct`` fallback."""
    normalized_domain = canonical_domain(domain)
    if not normalized_domain:
        raise ValueError("canonical domain is required for program identity")
    network = _normalized_part(affiliate_network, "direct")
    program = _normalized_part(program_name, "default")
    return f"program:{_digest(normalized_domain, network, program)}"


def candidate_dedupe_key(program_key: str, offer_name: str | None = None) -> str:
    """Run-scoped duplicate key; an absent offer uses an explicit ``default-offer`` fallback."""
    program = (program_key or "").strip()
    if not program:
        raise ValueError("program_identity_key is required for candidate deduplication")
    offer = _normalized_part(offer_name, "default-offer")
    return f"candidate:{_digest(program, offer)}"
