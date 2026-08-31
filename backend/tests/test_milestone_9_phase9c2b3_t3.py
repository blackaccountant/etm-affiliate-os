"""B3 contract checks: recipient is required only for allowed T3 facts."""
import pytest
from datetime import datetime, timezone
from app.outreach.cold_delivery_contracts import ColdT3DecisionContract
from app.outreach.contracts import OutreachError
from app.outreach.cold_recipient_resolution import ColdEphemeralRecipient

NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)

def _decision(decision, recipient):
    return ColdT3DecisionContract("a" * 36, "b" * 36, "c" * 64, NOW, "d" * 64, "e" * 64, (), recipient, decision, ("T3_ALLOWED",))

def test_blocked_t3_allows_no_recipient_but_allowed_requires_one():
    assert _decision("BLOCKED", None).recipient_fingerprint is None
    assert _decision("ALLOWED", "f" * 64).recipient_fingerprint == "f" * 64
    with pytest.raises(OutreachError): _decision("ALLOWED", None)

def test_t3_contract_carries_no_raw_recipient_field():
    assert not {"recipient", "recipient_email", "normalized_value"}.intersection(ColdT3DecisionContract.__dataclass_fields__)


def test_cold_recipient_is_redacted_and_has_no_value_export():
    recipient = ColdEphemeralRecipient("EMAIL", "recipient@Example.com")
    assert "recipient@" not in repr(recipient)
    assert str(recipient) == repr(recipient)
    assert not hasattr(recipient, "value")
    assert len(recipient.fingerprint()) == 64
