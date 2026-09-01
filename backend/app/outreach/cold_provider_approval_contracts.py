"""Cold commercial approval is explicit: generic EMAIL capability is irrelevant."""
from dataclasses import dataclass
from app.outreach.contracts import OutreachError, required_text

@dataclass(frozen=True)
class ColdProviderApproval:
    provider_key: str; provider_contract_version: str; channel: str = "EMAIL"; commercial_class: str = "COLD_B2B"
    approval_state: str = "APPROVED"; native_idempotency: str = "DECLARED"; provider_reference_support: bool = True
    reconciliation_lookup: bool = True; retention_semantics: str = "BOUNDED"; sender_domain_readiness: str = "REQUIRED"
    suppression_bounce_complaint_capability: str = "DECLARED"
    def __post_init__(self):
        object.__setattr__(self, "provider_key", required_text(self.provider_key, "provider_key", 64))
        object.__setattr__(self, "provider_contract_version", required_text(self.provider_contract_version, "provider_contract_version", 128))
        if self.channel != "EMAIL" or self.commercial_class != "COLD_B2B" or self.approval_state != "APPROVED":
            raise OutreachError("COLD_PROVIDER_NOT_APPROVED", "provider is not explicitly approved for cold B2B")

class ColdProviderApprovalRegistry:
    def __init__(self, approvals=()): self._approvals = tuple(approvals)

    @staticmethod
    def _is_explicitly_approved(item):
        """Fail closed: no non-empty or unknown declaration is capability proof."""
        return (
            isinstance(item, ColdProviderApproval)
            and isinstance(item.provider_key, str) and bool(item.provider_key.strip())
            and isinstance(item.provider_contract_version, str) and bool(item.provider_contract_version.strip())
            and item.channel == "EMAIL"
            and item.commercial_class == "COLD_B2B"
            and item.approval_state == "APPROVED"
            and item.native_idempotency == "DECLARED"
            and item.provider_reference_support is True
            and item.reconciliation_lookup is True
            and item.retention_semantics == "BOUNDED"
            and item.sender_domain_readiness == "REQUIRED"
            and item.suppression_bounce_complaint_capability == "DECLARED"
        )

    def select(self):
        approved = [item for item in self._approvals if self._is_explicitly_approved(item) and item.provider_key.lower() != "resend"]
        if len(approved) != 1: raise OutreachError("COLD_PROVIDER_NOT_APPROVED", "no explicit cold provider approval")
        return approved[0]
