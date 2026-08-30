"""Typed contracts for the M6.1 audience foundation."""

from enum import Enum


class AudienceSubjectType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    ANONYMOUS = "ANONYMOUS"


class AudienceIdentityVerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FIRST_PARTY_VERIFIED = "FIRST_PARTY_VERIFIED"


class AudienceResearchRunStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AudienceSourceType(str, Enum):
    FIRST_PARTY_WEB = "FIRST_PARTY_WEB"
    FIRST_PARTY_APP = "FIRST_PARTY_APP"
    FIRST_PARTY_EMAIL = "FIRST_PARTY_EMAIL"
    PUBLIC_WEB = "PUBLIC_WEB"
    PUBLIC_SOCIAL = "PUBLIC_SOCIAL"
    BUSINESS_DIRECTORY = "BUSINESS_DIRECTORY"
    SEARCH = "SEARCH"
    AFFILIATE_TRAFFIC = "AFFILIATE_TRAFFIC"
    PARTNER = "PARTNER"
    CRM = "CRM"
    MANUAL = "MANUAL"
