"""Create one immutable, explicit, balanced allocation for an M10A9A shared cost."""
import hashlib
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.affiliate_financial.cost_allocation_contracts import (
    RecordSharedCostAllocationRequest,
    SharedCostAllocationLineRecord,
    SharedCostAllocationLineRequest,
    SharedCostAllocationRecord,
)
from app.attribution.contracts import AttributionIdempotencyConflict, canonical_fingerprint
from app.models.affiliate_cost_allocation import AffiliateCostAllocationBatch, AffiliateCostAllocationLine
from app.repositories.affiliate_cost_allocation_repository import AffiliateCostAllocationRepository


_TRACEABLE_CORRELATIONS = {
    "product_id": "product",
    "affiliate_program_id": "affiliate_program",
    "content_asset_id": "content_asset",
    "distribution_run_id": "distribution_run",
    "affiliate_link_id": "affiliate_link",
    "affiliate_conversion_id": "conversion",
    "affiliate_earning_id": "earning",
    "affiliate_payout_id": "payout",
    "affiliate_payout_attempt_id": "payout_attempt",
}


class AffiliateCostAllocationConflict(AttributionIdempotencyConflict):
    pass


class AffiliateCostAllocationService:
    def __init__(self, db):
        self.db = db
        self.allocations = AffiliateCostAllocationRepository(db)

    @staticmethod
    def _event_id(value):
        try:
            normalized = str(UUID(value)) if isinstance(value, str) else ""
        except ValueError:
            normalized = ""
        if normalized != value:
            raise ValueError("affiliate_cost_event_id must be a canonical UUID")
        return normalized

    @staticmethod
    def _text(value, pattern, field):
        normalized = value.strip().lower() if isinstance(value, str) else ""
        if not re.fullmatch(pattern, normalized):
            raise ValueError(f"{field} is invalid")
        return normalized

    @staticmethod
    def _amount(value):
        if not isinstance(value, Decimal):
            raise ValueError("allocation amount must be Decimal")
        try:
            quantized = value.quantize(Decimal("0.01"))
        except InvalidOperation:
            raise ValueError("allocation amount is invalid")
        if not value.is_finite() or value <= 0 or value != quantized:
            raise ValueError("allocation amount must be positive, finite, and quantized to cents")
        return quantized

    @classmethod
    def _normalized_request(cls, request):
        if not isinstance(request, RecordSharedCostAllocationRequest):
            raise ValueError("request must be RecordSharedCostAllocationRequest")
        event_id = cls._event_id(request.affiliate_cost_event_id)
        policy = cls._text(request.policy_version, r"[a-z][a-z0-9._-]{0,127}", "policy_version")
        namespace = cls._text(request.source_namespace, r"[a-z][a-z0-9.-]{0,62}", "source_namespace")
        if not isinstance(request.source_event_key, str) or not request.source_event_key.strip():
            raise ValueError("source_event_key is required")
        if not isinstance(request.allocations, tuple) or not request.allocations:
            raise ValueError("allocations must be a non-empty tuple")
        normalized = []
        seen = set()
        for line in request.allocations:
            if not isinstance(line, SharedCostAllocationLineRequest):
                raise ValueError("allocation line has invalid type")
            earning_id = line.affiliate_earning_id
            if isinstance(earning_id, bool) or not isinstance(earning_id, int) or earning_id < 1:
                raise ValueError("affiliate_earning_id must be a positive integer")
            if earning_id in seen:
                raise ValueError("duplicate affiliate earning allocation")
            seen.add(earning_id)
            normalized.append((earning_id, cls._amount(line.amount)))
        return event_id, tuple(sorted(normalized)), policy, namespace, request.source_event_key.strip()

    @staticmethod
    def _assert_lineages(cost, entries, rows):
        by_earning = {row.earning: row for row in rows}
        if len(by_earning) != len(entries):
            raise ValueError("every allocation target must be an explicit settled earning")
        if cost.content_generation_run_id is not None or cost.outreach_provider_dispatch_id is not None:
            raise ValueError("shared cost contains an unsupported operational correlation")
        for earning_id, _ in entries:
            lineage = by_earning.get(earning_id)
            if lineage is None or lineage.currency != cost.currency:
                raise ValueError("allocation target currency does not match shared cost currency")
            for cost_field, lineage_field in _TRACEABLE_CORRELATIONS.items():
                value = getattr(cost, cost_field)
                if value is not None and value != getattr(lineage, lineage_field):
                    raise ValueError(f"allocation target contradicts {cost_field}")

    def record(self, request: RecordSharedCostAllocationRequest) -> SharedCostAllocationRecord:
        event_id, entries, policy, namespace, source_key = self._normalized_request(request)
        digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        cost = self.allocations.lock_cost_event(event_id)
        if cost is None:
            self.db.rollback()
            raise ValueError("affiliate cost event does not exist")
        fingerprint = canonical_fingerprint("m10a9c-shared-cost-allocation-v1", {
            "affiliate_cost_event_id": event_id,
            "affiliate_cost_event_fingerprint": cost.fingerprint,
            "allocations": [{"affiliate_earning_id": earning_id, "amount": str(amount)} for earning_id, amount in entries],
            "policy_version": policy,
            "source_namespace": namespace,
            "source_event_digest": digest,
        })
        existing_source = self.allocations.batch_by_source(namespace, digest)
        if existing_source is not None:
            return self._same_or_conflict(existing_source, fingerprint)
        existing_cost = self.allocations.batch_by_cost_event(event_id)
        if existing_cost is not None:
            return self._same_or_conflict(existing_cost, fingerprint)
        if cost.allocation_scope != "shared":
            self.db.rollback()
            raise ValueError("only shared affiliate cost events may be allocated")
        total = sum((amount for _, amount in entries), Decimal("0.00"))
        if total != Decimal(str(cost.amount)):
            self.db.rollback()
            raise ValueError("allocation amounts must exactly equal the shared cost amount")
        try:
            rows = self.allocations.settled_lineages(earning_id for earning_id, _ in entries)
            self._assert_lineages(cost, entries, rows)
        except Exception:
            self.db.rollback()
            raise
        batch = AffiliateCostAllocationBatch(
            affiliate_cost_event_id=event_id,
            allocated_amount=total,
            currency=cost.currency,
            policy_version=policy,
            source_namespace=namespace,
            source_event_digest=digest,
            fingerprint=fingerprint,
        )
        lines = [AffiliateCostAllocationLine(
            allocation_batch_id="",
            affiliate_earning_id=earning_id,
            amount=amount,
            fingerprint=canonical_fingerprint("m10a9c-shared-cost-allocation-line-v1", {
                "batch_fingerprint": fingerprint,
                "affiliate_earning_id": earning_id,
                "amount": str(amount),
            }),
        ) for earning_id, amount in entries]
        try:
            self.allocations.add(batch, lines)
            self.db.commit()
            self.db.refresh(batch)
            return self._record(batch)
        except IntegrityError:
            self.db.rollback()
            existing = self.allocations.batch_by_cost_event(event_id) or self.allocations.batch_by_source(namespace, digest)
            if existing is None:
                raise
            return self._same_or_conflict(existing, fingerprint)

    def _same_or_conflict(self, existing, fingerprint):
        if existing.fingerprint != fingerprint:
            self.db.rollback()
            raise AffiliateCostAllocationConflict("conflicting shared-cost allocation replay")
        record = self._record(existing)
        self.db.commit()
        return record

    def _record(self, batch):
        lines = self.allocations.lines_for_batch(batch.id)
        return SharedCostAllocationRecord(
            batch.id,
            batch.affiliate_cost_event_id,
            Decimal(str(batch.allocated_amount)),
            batch.currency,
            batch.policy_version,
            batch.source_namespace,
            batch.source_event_digest,
            batch.fingerprint,
            tuple(SharedCostAllocationLineRecord(
                line.affiliate_earning_id, Decimal(str(line.amount)), line.fingerprint,
            ) for line in lines),
        )
