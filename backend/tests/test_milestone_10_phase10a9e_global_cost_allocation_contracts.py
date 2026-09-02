from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.affiliate_financial.global_cost_allocation_contracts import (
    GlobalCostAllocationLineRequest,
    GlobalCostAllocationRecord,
    RecordGlobalCostAllocationRequest,
)
from app.services.affiliate_global_cost_allocation_service import (
    AffiliateGlobalCostAllocationService,
)


EVENT_ID = "11111111-1111-1111-1111-111111111111"


def request(**values):
    data = {
        "affiliate_cost_event_id": EVENT_ID,
        "allocations": (
            GlobalCostAllocationLineRequest(
                affiliate_earning_id=2,
                amount=Decimal("20.00"),
            ),
            GlobalCostAllocationLineRequest(
                affiliate_earning_id=1,
                amount=Decimal("10.00"),
            ),
        ),
        "policy_version": "global-v1",
        "source_namespace": "m10a9e.test",
        "source_event_key": "event-1",
    }
    data.update(values)
    return RecordGlobalCostAllocationRequest(**data)


def test_request_and_line_contracts_are_frozen():
    line = GlobalCostAllocationLineRequest(
        affiliate_earning_id=1,
        amount=Decimal("10.00"),
    )

    with pytest.raises(FrozenInstanceError):
        line.amount = Decimal("20.00")

    item = request()

    with pytest.raises(FrozenInstanceError):
        item.policy_version = "changed"


def test_normalization_is_deterministic_and_sorts_explicit_targets():
    normalized = AffiliateGlobalCostAllocationService._normalized_request(
        request()
    )

    assert normalized[0] == EVENT_ID
    assert normalized[1] == (
        (1, Decimal("10.00")),
        (2, Decimal("20.00")),
    )
    assert normalized[2] == "global-v1"
    assert normalized[3] == "m10a9e.test"
    assert normalized[4] == "event-1"


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0.00"),
        Decimal("-1.00"),
        Decimal("1.001"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_allocation_amount_requires_positive_finite_decimal_cents(amount):
    bad = request(
        allocations=(
            GlobalCostAllocationLineRequest(
                affiliate_earning_id=1,
                amount=amount,
            ),
        )
    )

    with pytest.raises(ValueError):
        AffiliateGlobalCostAllocationService._normalized_request(bad)


def test_duplicate_targets_and_empty_allocations_fail_closed():
    duplicate = request(
        allocations=(
            GlobalCostAllocationLineRequest(1, Decimal("10.00")),
            GlobalCostAllocationLineRequest(1, Decimal("20.00")),
        )
    )

    with pytest.raises(ValueError):
        AffiliateGlobalCostAllocationService._normalized_request(
            duplicate
        )

    with pytest.raises(ValueError):
        AffiliateGlobalCostAllocationService._normalized_request(
            request(allocations=())
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("affiliate_cost_event_id", "not-a-uuid"),
        ("policy_version", ""),
        ("policy_version", "1bad"),
        ("source_namespace", ""),
        ("source_namespace", "BAD SPACE"),
        ("source_event_key", ""),
    ],
)
def test_invalid_identity_fields_fail_closed(field, value):
    with pytest.raises(ValueError):
        AffiliateGlobalCostAllocationService._normalized_request(
            request(**{field: value})
        )


def test_record_contract_preserves_decimal_lines_and_exact_fields():
    record = GlobalCostAllocationRecord(
        id="batch-1",
        affiliate_cost_event_id=EVENT_ID,
        allocated_amount=Decimal("30.00"),
        currency="USD",
        policy_version="global-v1",
        source_namespace="m10a9e.test",
        source_event_digest="a" * 64,
        fingerprint="b" * 64,
        allocations=(),
    )

    assert record.allocated_amount == Decimal("30.00")
    assert len(record.__dataclass_fields__) == 9

    with pytest.raises(FrozenInstanceError):
        record.currency = "EUR"
