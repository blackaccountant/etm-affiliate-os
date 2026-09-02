from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal
from uuid import uuid4

import pytest

from app.affiliate_financial.cost_allocation_contracts import (
    RecordSharedCostAllocationRequest,
    SharedCostAllocationLineRecord,
    SharedCostAllocationLineRequest,
    SharedCostAllocationRecord,
)
from app.services.affiliate_cost_allocation_service import AffiliateCostAllocationService


def request(**values):
    base = dict(
        affiliate_cost_event_id=str(uuid4()),
        allocations=(SharedCostAllocationLineRequest(2, Decimal("2.00")), SharedCostAllocationLineRequest(1, Decimal("1.00"))),
        policy_version=" Shared_Cost_V1 ",
        source_namespace=" M10A9C.Test ",
        source_event_key=" event-1 ",
    )
    base.update(values)
    return RecordSharedCostAllocationRequest(**base)


def test_request_and_line_contracts_are_frozen():
    line = SharedCostAllocationLineRequest(1, Decimal("1.00"))
    value = request(allocations=(line,))
    with pytest.raises(FrozenInstanceError):
        line.amount = Decimal("2.00")
    with pytest.raises(FrozenInstanceError):
        value.policy_version = "v2"


def test_normalization_is_deterministic_and_sorts_explicit_targets():
    event_id, lines, policy, namespace, key = AffiliateCostAllocationService._normalized_request(request())
    assert event_id and lines == ((1, Decimal("1.00")), (2, Decimal("2.00")))
    assert (policy, namespace, key) == ("shared_cost_v1", "m10a9c.test", "event-1")


@pytest.mark.parametrize("amount", ["1.00", 1, Decimal("0"), Decimal("-1.00"), Decimal("1.001"), Decimal("NaN"), Decimal("Infinity")])
def test_allocation_amount_requires_positive_finite_decimal_cents(amount):
    with pytest.raises(ValueError):
        AffiliateCostAllocationService._amount(amount)


def test_duplicate_targets_and_empty_allocations_fail_closed():
    duplicate = (SharedCostAllocationLineRequest(1, Decimal("1.00")), SharedCostAllocationLineRequest(1, Decimal("2.00")))
    with pytest.raises(ValueError, match="duplicate"):
        AffiliateCostAllocationService._normalized_request(request(allocations=duplicate))
    with pytest.raises(ValueError, match="non-empty tuple"):
        AffiliateCostAllocationService._normalized_request(request(allocations=()))


@pytest.mark.parametrize("field,value", [("affiliate_cost_event_id", "not-a-uuid"), ("policy_version", ""), ("source_namespace", "Bad Namespace"), ("source_event_key", "")])
def test_invalid_identity_fields_fail_closed(field, value):
    with pytest.raises(ValueError):
        AffiliateCostAllocationService._normalized_request(request(**{field: value}))


def test_record_contract_preserves_decimal_lines_and_exact_fields():
    line = SharedCostAllocationLineRecord(1, Decimal("3.00"), "a" * 64)
    record = SharedCostAllocationRecord(str(uuid4()), str(uuid4()), Decimal("3.00"), "USD", "v1", "m10a9c.test", "b" * 64, "c" * 64, (line,))
    assert set(asdict(record)) == {"id", "affiliate_cost_event_id", "allocated_amount", "currency", "policy_version", "source_namespace", "source_event_digest", "fingerprint", "allocations"}
    assert isinstance(record.allocated_amount, Decimal) and isinstance(record.allocations[0].amount, Decimal)
    with pytest.raises(FrozenInstanceError):
        record.currency = "EUR"
