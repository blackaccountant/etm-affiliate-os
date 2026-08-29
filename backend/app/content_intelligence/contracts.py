"""Canonical contracts for the durable content intelligence ledger."""

from __future__ import annotations

from enum import Enum


class ContentType(str, Enum):
    ARTICLE = "ARTICLE"
    BLOG_POST = "BLOG_POST"
    SOCIAL_POST = "SOCIAL_POST"
    SHORT_VIDEO_SCRIPT = "SHORT_VIDEO_SCRIPT"
    LONG_VIDEO_SCRIPT = "LONG_VIDEO_SCRIPT"
    EMAIL = "EMAIL"
    LANDING_PAGE_COPY = "LANDING_PAGE_COPY"
    PRODUCT_REVIEW = "PRODUCT_REVIEW"
    COMPARISON = "COMPARISON"
    BUYER_GUIDE = "BUYER_GUIDE"
    AD_COPY = "AD_COPY"


class EvidenceUsageRole(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    ECONOMICS = "ECONOMICS"
    FEATURE = "FEATURE"
    CTA_SUPPORT = "CTA_SUPPORT"
    DISCLOSURE_SUPPORT = "DISCLOSURE_SUPPORT"


class ContentBriefStatus(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

    @classmethod
    def legal_transition(cls, from_status: str, to_status: str) -> bool:
        allowed = {
            cls.CREATED.value: {cls.READY.value},
            cls.READY.value: {cls.GENERATING.value, cls.REJECTED.value},
            cls.GENERATING.value: {cls.COMPLETED.value, cls.FAILED.value},
        }
        return to_status in allowed.get(from_status, set())


class ContentGenerationRunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @classmethod
    def legal_transition(cls, from_status: str, to_status: str) -> bool:
        allowed = {
            cls.CREATED.value: {cls.RUNNING.value},
            cls.RUNNING.value: {cls.RETRY_WAIT.value, cls.COMPLETED.value, cls.FAILED.value},
            cls.RETRY_WAIT.value: {cls.RUNNING.value},
        }
        return to_status in allowed.get(from_status, set())
