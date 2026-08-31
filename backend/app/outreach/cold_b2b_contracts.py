"""Immutable contracts for provider-independent M9C2A authorization."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.outreach.contracts import OutreachError, aware_utc, fingerprint, required_text, sha256_fingerprint

COLD_B2B_ELIGIBILITY_POLICY_VERSION = "cold-b2b-eligibility-v1"
COLD_B2B_FREQUENCY_POLICY_VERSION = "cold-b2b-frequency-v1"
ORGANIZATION_EVIDENCE_SCHEMA_VERSION = "cold-organization-evidence-v1"
POLICY_SELECTION_SCHEMA_VERSION = "cold-policy-selection-v1"
_PURPOSE = re.compile(r"^cold_b2b:[a-z0-9][a-z0-9_-]{0,63}$")
_SOURCE_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]{0,99}$")


class ColdAuthorizationState(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"


class ColdRequestedAction(str, Enum):
    INITIAL = "INITIAL"
    FOLLOW_UP = "FOLLOW_UP"


@dataclass(frozen=True)
class ColdB2BPolicyProfile:
    key: str
    version: str
    minimum_follow_up_spacing: timedelta
    maximum_follow_ups: int


DEFAULT_COLD_B2B_POLICY_PROFILE = ColdB2BPolicyProfile("cold-b2b-default-v1", "cold-b2b-profile-v1", timedelta(days=7), 3)
SUPPORTED_COLD_B2B_POLICY_PROFILES = {DEFAULT_COLD_B2B_POLICY_PROFILE.key: DEFAULT_COLD_B2B_POLICY_PROFILE}
APPROVED_ORGANIZATION_EVIDENCE_SOURCES = frozenset({"ORGANIZATION_REGISTRY", "VERIFIED_BUSINESS_SOURCE"})


def _identifier(value, field):
    return required_text(value, field, 36)


def opaque_source_namespace(value):
    value = required_text(value, "source_namespace", 100)
    if not _SOURCE_NAMESPACE.fullmatch(value):
        raise OutreachError("INVALID_SOURCE_NAMESPACE", "source_namespace must be a canonical non-PII token")
    return value


@dataclass(frozen=True)
class OrganizationEvidenceAuthorityReference:
    organization_evidence_id: str
    expected_fingerprint: str

    def __post_init__(self):
        object.__setattr__(self, "organization_evidence_id", _identifier(self.organization_evidence_id, "organization_evidence_id"))
        object.__setattr__(self, "expected_fingerprint", fingerprint(self.expected_fingerprint, "organization_evidence_fingerprint"))


@dataclass(frozen=True)
class PolicySelectionAuthorityReference:
    policy_selection_id: str
    expected_fingerprint: str

    def __post_init__(self):
        object.__setattr__(self, "policy_selection_id", _identifier(self.policy_selection_id, "policy_selection_id"))
        object.__setattr__(self, "expected_fingerprint", fingerprint(self.expected_fingerprint, "policy_selection_fingerprint"))


@dataclass(frozen=True)
class CreateColdProspectingAuthorizationRequest:
    lead_id: str
    contact_point_id: str
    purpose_key: str
    requested_action: str
    source_namespace: str
    source_event_key: str
    organization_evidence: OrganizationEvidenceAuthorityReference
    policy_selection: PolicySelectionAuthorityReference
    message_content_fingerprint: str
    evaluated_at: datetime

    def __post_init__(self):
        object.__setattr__(self, "lead_id", _identifier(self.lead_id, "lead_id"))
        object.__setattr__(self, "contact_point_id", _identifier(self.contact_point_id, "contact_point_id"))
        if not isinstance(self.purpose_key, str) or self.purpose_key != self.purpose_key.strip() or not _PURPOSE.fullmatch(self.purpose_key):
            raise OutreachError("INVALID_COLD_PURPOSE", "purpose_key must be canonical cold_b2b:<slug>")
        object.__setattr__(self, "requested_action", ColdRequestedAction(self.requested_action).value)
        object.__setattr__(self, "source_namespace", opaque_source_namespace(self.source_namespace))
        object.__setattr__(self, "source_event_key", fingerprint(self.source_event_key, "source_event_key"))
        if not isinstance(self.organization_evidence, OrganizationEvidenceAuthorityReference) or not isinstance(self.policy_selection, PolicySelectionAuthorityReference):
            raise OutreachError("INVALID_CONTRACT", "authorization requires durable organization and policy authorities")
        object.__setattr__(self, "message_content_fingerprint", fingerprint(self.message_content_fingerprint, "message_content_fingerprint"))
        object.__setattr__(self, "evaluated_at", aware_utc(self.evaluated_at, "evaluated_at"))

    @property
    def purpose_family(self):
        return self.purpose_key.removeprefix("cold_b2b:")

    @property
    def request_fingerprint(self):
        return sha256_fingerprint({"action": self.requested_action, "channel": "EMAIL", "contact_point_id": self.contact_point_id, "eligibility_policy_version": COLD_B2B_ELIGIBILITY_POLICY_VERSION, "frequency_policy_version": COLD_B2B_FREQUENCY_POLICY_VERSION, "lead_id": self.lead_id, "message_content_fingerprint": self.message_content_fingerprint, "organization_evidence_id": self.organization_evidence.organization_evidence_id, "organization_evidence_fingerprint": self.organization_evidence.expected_fingerprint, "policy_selection_id": self.policy_selection.policy_selection_id, "policy_selection_fingerprint": self.policy_selection.expected_fingerprint, "purpose_key": self.purpose_key})


@dataclass(frozen=True)
class ProspectingEligibilityAssessment:
    state: str
    reason_codes: tuple[str, ...]
    policy_version: str
    frequency_policy_version: str
    policy_profile_key: str
    policy_profile_version: str
    decision_fingerprint: str

    @property
    def eligible(self):
        return self.state == ColdAuthorizationState.ELIGIBLE.value
