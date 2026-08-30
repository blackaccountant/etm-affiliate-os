"""Immutable contracts for deterministic M8B contact normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.crm.contracts import CRMError, ContactPointKind


NORMALIZATION_VERSION = "crm-contact-normalization-v1"
_REGION = re.compile(r"^[A-Z]{2}$")


class SocialPlatform(str, Enum):
    LINKEDIN = "linkedin"
    YOUTUBE = "youtube"


class ContactNormalizationFailure(str, Enum):
    INVALID_CONTACT_VALUE = "INVALID_CONTACT_VALUE"
    MISSING_COUNTRY_CONTEXT = "MISSING_COUNTRY_CONTEXT"
    UNSUPPORTED_CONTACT_FORMAT = "UNSUPPORTED_CONTACT_FORMAT"
    UNSUPPORTED_SOCIAL_PLATFORM = "UNSUPPORTED_SOCIAL_PLATFORM"
    AMBIGUOUS_CONTACT_VALUE = "AMBIGUOUS_CONTACT_VALUE"


class ContactNormalizationError(CRMError):
    """Typed normalization failure that never includes the raw contact value."""

    def __init__(self, category: ContactNormalizationFailure | str, message: str):
        super().__init__(ContactNormalizationFailure(category).value, message)


@dataclass(frozen=True)
class ContactNormalizationContext:
    country_region: str | None = None
    social_platform: str | None = None

    def __post_init__(self) -> None:
        if self.country_region is not None:
            if not isinstance(self.country_region, str):
                raise ContactNormalizationError("INVALID_CONTACT_VALUE", "country_region must be an ISO region code")
            region = self.country_region.strip().upper()
            if not _REGION.fullmatch(region):
                raise ContactNormalizationError("INVALID_CONTACT_VALUE", "country_region must be an ISO alpha-2 region code")
            object.__setattr__(self, "country_region", region)
        if self.social_platform is not None:
            try:
                platform = SocialPlatform(self.social_platform.strip().lower()).value
            except (AttributeError, ValueError) as exc:
                raise ContactNormalizationError("UNSUPPORTED_SOCIAL_PLATFORM", "social platform is not supported") from exc
            object.__setattr__(self, "social_platform", platform)


@dataclass(frozen=True)
class ContactNormalizationCandidate:
    kind: str
    raw_value: str = field(repr=False)
    context: ContactNormalizationContext = field(default_factory=ContactNormalizationContext)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", ContactPointKind(self.kind).value)
        except (TypeError, ValueError) as exc:
            raise ContactNormalizationError("UNSUPPORTED_CONTACT_FORMAT", "contact-point kind is not supported") from exc
        if not isinstance(self.raw_value, str) or not self.raw_value.strip():
            raise ContactNormalizationError("INVALID_CONTACT_VALUE", "contact value is required")
        if len(self.raw_value) > 4096:
            raise ContactNormalizationError("INVALID_CONTACT_VALUE", "contact value is too long")
        if not isinstance(self.context, ContactNormalizationContext):
            raise ContactNormalizationError("INVALID_CONTACT_VALUE", "normalization context must be typed")


@dataclass(frozen=True)
class NormalizedContactPoint:
    kind: str
    normalized_value: str
    normalization_version: str = NORMALIZATION_VERSION

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "kind", ContactPointKind(self.kind).value)
        except (TypeError, ValueError) as exc:
            raise ContactNormalizationError("UNSUPPORTED_CONTACT_FORMAT", "normalized contact-point kind is not supported") from exc
        if not isinstance(self.normalized_value, str) or not self.normalized_value:
            raise ContactNormalizationError("INVALID_CONTACT_VALUE", "normalized contact value is required")
        if self.normalization_version != NORMALIZATION_VERSION:
            raise ContactNormalizationError("UNSUPPORTED_CONTACT_FORMAT", "normalization version is not supported")
