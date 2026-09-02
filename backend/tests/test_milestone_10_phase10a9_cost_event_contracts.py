from dataclasses import FrozenInstanceError
from decimal import Decimal
import pytest
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest, AffiliateCostEventRecord
from app.services.affiliate_cost_event_service import AffiliateCostEventService

def request(**values):
    base=dict(amount=Decimal("12.34"),currency=" usd ",cost_type=" Content_Generation ",allocation_scope="direct",source_namespace="M10A9A.COST",source_event_key="event-1",affiliate_program_id=1);base.update(values);return RecordAffiliateCostEventRequest(**base)

def test_request_is_frozen_and_shapes_direct_shared_global_contracts():
    value=request(); assert value.amount==Decimal("12.34")
    with pytest.raises(FrozenInstanceError): value.currency="EUR"
    assert request(allocation_scope="shared",affiliate_program_id=None).allocation_scope=="shared"
    assert request(allocation_scope="global",affiliate_program_id=None).allocation_scope=="global"

@pytest.mark.parametrize("amount",[Decimal("0"),Decimal("-1"),"NaN","Infinity"])
def test_amount_validation_rejects_nonpositive_or_nonfinite(amount):
    with pytest.raises(ValueError): AffiliateCostEventService._amount(amount)

def test_normalizers_validate_currency_type_namespace_and_scope():
    assert AffiliateCostEventService._currency(" usd ")=="USD"
    assert AffiliateCostEventService._text(" Content_Generation ",r"[a-z][a-z0-9._-]{0,62}","cost_type")=="content_generation"
    assert AffiliateCostEventService._text("M10A9A.COST",r"[a-z][a-z0-9.-]{0,62}","source_namespace")=="m10a9a.cost"
    for value in ("US","USDD","1SD"):
        with pytest.raises(ValueError): AffiliateCostEventService._currency(value)
    for value in ("1bad","bad space"):
        with pytest.raises(ValueError): AffiliateCostEventService._text(value,r"[a-z][a-z0-9._-]{0,62}","cost_type")
