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


class AudienceSignalType(str, Enum):
    PROBLEM = "PROBLEM"
    INTEREST = "INTEREST"
    INTENT = "INTENT"
    PURCHASE = "PURCHASE"
    ENGAGEMENT = "ENGAGEMENT"
    BUSINESS_NEED = "BUSINESS_NEED"


class AudienceIntentStage(str, Enum):
    RESEARCH = "RESEARCH"
    COMPARE = "COMPARE"
    EVALUATE = "EVALUATE"
    PRICING = "PRICING"
    PURCHASE_REQUEST = "PURCHASE_REQUEST"


class AudienceSignalError(ValueError):
    """A safe, typed rejection from the signal validation boundary."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
