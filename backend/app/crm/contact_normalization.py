"""Pure, provider-neutral M8B contact normalization."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit

import idna
import phonenumbers

from app.crm.contact_normalization_contracts import (
    ContactNormalizationCandidate,
    ContactNormalizationError,
    NormalizedContactPoint,
    SocialPlatform,
)
from app.crm.contracts import ContactPointKind


_ASCII_ATEXT = frozenset("!#$%&'*+-/=?^_`{|}~.")
_HEX = frozenset("0123456789abcdefABCDEF")
_TELEGRAM_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_TELEGRAM_RESERVED = frozenset({"joinchat", "addstickers", "addemoji", "c", "s", "share", "proxy"})
_LINKEDIN_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
_YOUTUBE_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$")
_YOUTUBE_CHANNEL = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_PHONE_INPUT = re.compile(r"^[+0-9().\-\s]+$")


def _error(category: str, message: str):
    raise ContactNormalizationError(category, message)


def _trimmed_nfc(value: str) -> str:
    result = unicodedata.normalize("NFC", value.strip())
    if not result or any(unicodedata.category(char) in {"Cc", "Cs"} for char in result):
        _error("INVALID_CONTACT_VALUE", "contact value contains invalid characters")
    return result


def _idna_host(value: str) -> str:
    if not value or value.endswith(".") or any(char.isspace() for char in value):
        _error("INVALID_CONTACT_VALUE", "domain or hostname is invalid")
    try:
        return idna.encode(value.casefold(), uts46=False, std3_rules=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as exc:
        raise ContactNormalizationError("INVALID_CONTACT_VALUE", "domain or hostname is invalid") from exc


def normalize_email(raw_value: str) -> str:
    value = _trimmed_nfc(raw_value)
    if value.count("@") != 1:
        _error("INVALID_CONTACT_VALUE", "email must contain one unquoted mailbox separator")
    local, domain = value.split("@", 1)
    if not local or not domain:
        _error("INVALID_CONTACT_VALUE", "email mailbox and domain are required")
    if '"' in local or any(char in value for char in "()<>[]:;\\,"):
        _error("UNSUPPORTED_CONTACT_FORMAT", "quoted, commented, or literal email forms are unsupported")
    if local.startswith(".") or local.endswith(".") or ".." in local:
        _error("INVALID_CONTACT_VALUE", "email local part has invalid dot placement")
    for char in local:
        category = unicodedata.category(char)
        if char.isascii():
            if not (char.isalnum() or char in _ASCII_ATEXT):
                _error("INVALID_CONTACT_VALUE", "email local part contains unsupported characters")
        elif category[0] not in {"L", "N", "M"}:
            _error("UNSUPPORTED_CONTACT_FORMAT", "internationalized email local part is unsupported")
    canonical_domain = _idna_host(domain)
    if len(local.encode("utf-8")) > 64 or len(f"{local}@{canonical_domain}".encode("utf-8")) > 254:
        _error("INVALID_CONTACT_VALUE", "email exceeds supported length")
    return f"{local}@{canonical_domain}"


def normalize_phone(raw_value: str, country_region: str | None = None) -> str:
    value = _trimmed_nfc(raw_value)
    if not _PHONE_INPUT.fullmatch(value) or value.count("+") > 1 or ("+" in value and not value.startswith("+")):
        _error("AMBIGUOUS_CONTACT_VALUE", "phone input must contain exactly one number")
    if not value.startswith("+") and country_region is None:
        _error("MISSING_COUNTRY_CONTEXT", "national phone input requires explicit country_region")
    try:
        parsed = phonenumbers.parse(value, None if value.startswith("+") else country_region)
    except phonenumbers.NumberParseException as exc:
        raise ContactNormalizationError("INVALID_CONTACT_VALUE", "phone number is invalid") from exc
    if parsed.extension:
        _error("UNSUPPORTED_CONTACT_FORMAT", "phone extensions are unsupported")
    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        _error("INVALID_CONTACT_VALUE", "phone number is invalid")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_telegram(raw_value: str) -> str:
    value = _trimmed_nfc(raw_value)
    if "://" in value:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ContactNormalizationError("UNSUPPORTED_CONTACT_FORMAT", "Telegram URL is unsupported") from exc
        if parsed.scheme.lower() != "https" or parsed.hostname is None or parsed.hostname.lower() not in {"t.me", "telegram.me"}:
            _error("UNSUPPORTED_CONTACT_FORMAT", "Telegram URL is unsupported")
        if parsed.username is not None or parsed.password is not None or port is not None or parsed.query or parsed.fragment:
            _error("UNSUPPORTED_CONTACT_FORMAT", "Telegram URL contains unsupported components")
        path = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
        if path.endswith("/"):
            path = path[:-1]
        if not path or "/" in path:
            _error("UNSUPPORTED_CONTACT_FORMAT", "Telegram link is not a public username identity")
        value = path
    elif value.startswith("@"):
        value = value[1:]
    if value.startswith("+") or value.lower() in _TELEGRAM_RESERVED or not _TELEGRAM_USERNAME.fullmatch(value):
        _error("INVALID_CONTACT_VALUE", "Telegram username is invalid or unsupported")
    return value.lower()


def _normalize_percent_component(value: str, component: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%":
            if index + 2 >= len(value) or value[index + 1] not in _HEX or value[index + 2] not in _HEX:
                _error("INVALID_CONTACT_VALUE", f"website {component} contains a malformed percent escape")
            result.append("%" + value[index + 1:index + 3].upper())
            index += 3
            continue
        if ord(char) < 32 or ord(char) == 127:
            _error("INVALID_CONTACT_VALUE", f"website {component} contains invalid characters")
        result.append(quote(char, safe="") if not char.isascii() else char)
        index += 1
    return "".join(result)


def normalize_website(raw_value: str) -> str:
    value = _trimmed_nfc(raw_value)
    if any(char.isspace() for char in value):
        _error("INVALID_CONTACT_VALUE", "website URL cannot contain whitespace")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ContactNormalizationError("INVALID_CONTACT_VALUE", "website URL is malformed") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        _error("UNSUPPORTED_CONTACT_FORMAT", "website scheme is unsupported")
    if parsed.hostname is None:
        _error("INVALID_CONTACT_VALUE", "website hostname is required")
    if parsed.username is not None or parsed.password is not None:
        _error("UNSUPPORTED_CONTACT_FORMAT", "website credentials are unsupported")
    if parsed.netloc.endswith(":"):
        _error("INVALID_CONTACT_VALUE", "website port is malformed")
    hostname = _idna_host(parsed.hostname)
    if ":" in hostname:
        _error("UNSUPPORTED_CONTACT_FORMAT", "IP-literal website hosts are unsupported")
    default_port = 80 if scheme == "http" else 443
    netloc = hostname if port is None or port == default_port else f"{hostname}:{port}"
    path = _normalize_percent_component(parsed.path, "path")
    query = _normalize_percent_component(parsed.query, "query")
    return urlunsplit((scheme, netloc, path, query, ""))


def _social_url(value: str) -> tuple[str, list[str]]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ContactNormalizationError("UNSUPPORTED_CONTACT_FORMAT", "social profile URL is malformed") from exc
    if parsed.scheme.lower() != "https" or parsed.hostname is None or port is not None:
        _error("UNSUPPORTED_CONTACT_FORMAT", "social profile URL is unsupported")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        _error("UNSUPPORTED_CONTACT_FORMAT", "social profile URL contains unsupported components")
    host = parsed.hostname.lower()
    if host in {"linkedin.com", "www.linkedin.com"}:
        platform = SocialPlatform.LINKEDIN.value
    elif host in {"youtube.com", "www.youtube.com"}:
        platform = SocialPlatform.YOUTUBE.value
    else:
        _error("UNSUPPORTED_SOCIAL_PLATFORM", "social profile host is not supported")
    parts = [part for part in parsed.path.split("/") if part]
    return platform, parts


def _normalize_linkedin(parts: list[str]) -> str:
    if len(parts) != 2 or parts[0].lower() not in {"in", "company"} or not _LINKEDIN_SLUG.fullmatch(parts[1]):
        _error("AMBIGUOUS_CONTACT_VALUE", "LinkedIn input is not an explicit person or company profile")
    return f"linkedin:{parts[0].lower()}/{parts[1]}"


def _normalize_youtube(parts: list[str]) -> str:
    if len(parts) == 1 and parts[0].startswith("@"):
        handle = parts[0][1:]
        if not _YOUTUBE_HANDLE.fullmatch(handle):
            _error("INVALID_CONTACT_VALUE", "YouTube handle is invalid")
        return f"youtube:handle/{handle.lower()}"
    if len(parts) == 2 and parts[0].lower() == "handle":
        handle = parts[1].removeprefix("@")
        if not _YOUTUBE_HANDLE.fullmatch(handle):
            _error("INVALID_CONTACT_VALUE", "YouTube handle is invalid")
        return f"youtube:handle/{handle.lower()}"
    if len(parts) == 2 and parts[0].lower() == "channel" and _YOUTUBE_CHANNEL.fullmatch(parts[1]):
        return f"youtube:channel/{parts[1]}"
    _error("AMBIGUOUS_CONTACT_VALUE", "YouTube input is not an explicit handle or channel identity")


def normalize_social_profile(raw_value: str, social_platform: str | None = None) -> str:
    value = _trimmed_nfc(raw_value)
    detected_platform: str | None = None
    parts: list[str]
    if "://" in value:
        detected_platform, parts = _social_url(value)
    elif ":" in value:
        detected_platform, identity = value.split(":", 1)
        detected_platform = detected_platform.lower()
        if detected_platform not in {item.value for item in SocialPlatform}:
            _error("UNSUPPORTED_SOCIAL_PLATFORM", "social platform is not supported")
        parts = [part for part in identity.split("/") if part]
    else:
        if social_platform is None:
            _error("AMBIGUOUS_CONTACT_VALUE", "social profile input requires an explicit supported platform")
        detected_platform = social_platform
        if detected_platform == SocialPlatform.YOUTUBE.value and value.startswith("@"):
            parts = [value]
        else:
            parts = [part for part in value.split("/") if part]
    if social_platform is not None and detected_platform != social_platform:
        _error("AMBIGUOUS_CONTACT_VALUE", "social profile platform conflicts with explicit context")
    if detected_platform == SocialPlatform.LINKEDIN.value:
        return _normalize_linkedin(parts)
    if detected_platform == SocialPlatform.YOUTUBE.value:
        return _normalize_youtube(parts)
    _error("UNSUPPORTED_SOCIAL_PLATFORM", "social platform is not supported")


def normalize_contact_point(candidate: ContactNormalizationCandidate) -> NormalizedContactPoint:
    if not isinstance(candidate, ContactNormalizationCandidate):
        _error("INVALID_CONTACT_VALUE", "contact normalization candidate must be typed")
    kind = candidate.kind
    if kind == ContactPointKind.EMAIL.value:
        normalized = normalize_email(candidate.raw_value)
    elif kind == ContactPointKind.PHONE.value:
        normalized = normalize_phone(candidate.raw_value, candidate.context.country_region)
    elif kind == ContactPointKind.TELEGRAM.value:
        normalized = normalize_telegram(candidate.raw_value)
    elif kind == ContactPointKind.WEBSITE.value:
        normalized = normalize_website(candidate.raw_value)
    elif kind == ContactPointKind.SOCIAL_PROFILE.value:
        normalized = normalize_social_profile(candidate.raw_value, candidate.context.social_platform)
    else:  # ContactPointKind validation makes this defensive only.
        _error("UNSUPPORTED_CONTACT_FORMAT", "contact-point kind is unsupported")
    return NormalizedContactPoint(kind=kind, normalized_value=normalized)
