"""
ETM Affiliate OS
URL Normalizer

Provides deterministic URL normalization for product identity,
database lookup, deduplication, and intelligence fingerprinting.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """
    Convert equivalent website URLs into one canonical URL.

    Examples:

        hubspot.com
        www.hubspot.com
        http://hubspot.com
        https://hubspot.com
        https://www.hubspot.com/
        [https://www.hubspot.com/](https://www.hubspot.com/)

    become:

        https://hubspot.com/
    """

    if not url:
        raise ValueError("URL is required.")

    value = str(url).strip()

    # ---------------------------------------------------------
    # Remove Markdown link formatting
    # ---------------------------------------------------------

    if value.startswith("[") and "](" in value and value.endswith(")"):
        value = value.split("](", 1)[1][:-1].strip()

    # ---------------------------------------------------------
    # Remove surrounding whitespace
    # ---------------------------------------------------------

    value = value.strip()

    # ---------------------------------------------------------
    # Add HTTPS when scheme is missing
    # ---------------------------------------------------------

    if not value.lower().startswith(
        ("http://", "https://")
    ):
        value = f"https://{value}"

    # ---------------------------------------------------------
    # Parse URL
    # ---------------------------------------------------------

    parsed = urlsplit(value)

    if not parsed.netloc:
        raise ValueError(
            f"Invalid URL: {url}"
        )

    # ---------------------------------------------------------
    # Normalize hostname
    # ---------------------------------------------------------

    hostname = parsed.hostname

    if not hostname:
        raise ValueError(
            f"Invalid URL hostname: {url}"
        )

    hostname = hostname.lower().rstrip(".")

    # ---------------------------------------------------------
    # Remove www.
    #
    # This is intentional.
    #
    # ETM Affiliate OS is identifying the business/product,
    # not the specific hostname presentation.
    #
    # Therefore:
    #
    # www.hubspot.com
    # hubspot.com
    #
    # become the same identity.
    # ---------------------------------------------------------

    if hostname.startswith("www."):
        hostname = hostname[4:]

    # ---------------------------------------------------------
    # Canonical scheme
    #
    # Websites are represented using HTTPS.
    # ---------------------------------------------------------

    scheme = "https"

    # ---------------------------------------------------------
    # Normalize port
    #
    # Standard HTTP/HTTPS ports are removed.
    # Non-standard ports are retained.
    # ---------------------------------------------------------

    port = parsed.port

    if port in (80, 443):
        port = None

    if port is not None:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    # ---------------------------------------------------------
    # Normalize path
    # ---------------------------------------------------------

    path = parsed.path or "/"

    if not path.startswith("/"):
        path = f"/{path}"

    # Collapse repeated trailing slashes.
    #
    # /       -> /
    # ////    -> /
    # /abc/// -> /abc
    #

    path = path.rstrip("/") or "/"

    # ---------------------------------------------------------
    # Query strings
    #
    # Keep them for now.
    #
    # We will later decide whether tracking parameters such
    # as utm_source should be stripped at the identity layer.
    # ---------------------------------------------------------

    query = parsed.query

    # ---------------------------------------------------------
    # Fragments are never part of server-side product identity.
    # ---------------------------------------------------------

    fragment = ""

    # ---------------------------------------------------------
    # Build canonical URL
    # ---------------------------------------------------------

    normalized = urlunsplit(
        (
            scheme,
            netloc,
            path,
            query,
            fragment,
        )
    )

    return normalized


def normalize_domain(url: str) -> str:
    """
    Return the canonical hostname for a URL.
    """

    normalized = normalize_url(url)

    parsed = urlsplit(normalized)

    if not parsed.hostname:
        raise ValueError(
            f"Invalid normalized URL: {url}"
        )

    return parsed.hostname.lower()


__all__ = [
    "normalize_url",
    "normalize_domain",
]
