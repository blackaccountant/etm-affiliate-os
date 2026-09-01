from decimal import Decimal
import pytest
from app.affiliate_financial.adjustment_contracts import adjustment_fingerprint
def test_adjustment_contract_enforces_signed_bounded_types():
 assert len(adjustment_fingerprint(earning_id=1,program_id=1,adjustment_type="REVERSAL",adjustment_amount=Decimal("-1"),currency="USD",source_namespace="m10a7.adjustment",source_event_digest="a"*64))==64
 with pytest.raises(ValueError): adjustment_fingerprint(earning_id=1,program_id=1,adjustment_type="REVERSAL",adjustment_amount=Decimal("1"),currency="USD",source_namespace="m10a7.adjustment",source_event_digest="a"*64)
