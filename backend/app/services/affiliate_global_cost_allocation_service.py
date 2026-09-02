"""Create immutable, explicit, balanced allocations for M10A9A global costs."""

import hashlib
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.affiliate_financial.global_cost_allocation_contracts import (
    GlobalCostAllocationLineRecord,
    GlobalCostAllocationLineRequest,
    GlobalCostAllocationRecord,
    RecordGlobalCostAllocationRequest,
)
from app.attribution.contracts import (
    AttributionIdempotencyConflict,
    canonical_fingerprint,
)
from app.models.affiliate_global_cost_allocation import (
    AffiliateGlobalCostAllocationBatch,
    AffiliateGlobalCostAllocationLine,
)
from app.repositories.affiliate_global_cost_allocation_repository import (
    AffiliateGlobalCostAllocationRepository,
)


class AffiliateGlobalCostAllocationConflict(AttributionIdempotencyConflict):
    pass


class AffiliateGlobalCostAllocationService:
    def __init__(self, db):
        self.db = db
        self.allocations = AffiliateGlobalCostAllocationRepository(db)

    @staticmethod
    def _event_id(value):
        try:
            normalized = str(UUID(value)) if isinstance(value, str) else ""
        except ValueError:
            normalized = ""

        if normalized != value:
            raise ValueError(
                "affiliate_cost_event_id must be a canonical UUID"
            )

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

        if (
            not value.is_finite()
            or value <= 0
            or value != quantized
        ):
            raise ValueError(
                "allocation amount must be positive, finite, and quantized to cents"
            )

        return quantized

    @classmethod
    def _normalized_request(cls, request):
        if not isinstance(request, RecordGlobalCostAllocationRequest):
            raise ValueError(
                "request must be RecordGlobalCostAllocationRequest"
            )

        event_id = cls._event_id(request.affiliate_cost_event_id)

        policy = cls._text(
            request.policy_version,
            r"[a-z][a-z0-9._-]{0,127}",
            "policy_version",
        )

        namespace = cls._text(
            request.source_namespace,
            r"[a-z][a-z0-9.-]{0,62}",
            "source_namespace",
        )

        if (
            not isinstance(request.source_event_key, str)
            or not request.source_event_key.strip()
        ):
            raise ValueError("source_event_key is required")

        if (
            not isinstance(request.allocations, tuple)
            or not request.allocations
        ):
            raise ValueError("allocations must be a non-empty tuple")

        normalized = []
        seen = set()

        for line in request.allocations:
            if not isinstance(line, GlobalCostAllocationLineRequest):
                raise ValueError("allocation line has invalid type")

            earning_id = line.affiliate_earning_id

            if (
                isinstance(earning_id, bool)
                or not isinstance(earning_id, int)
                or earning_id < 1
            ):
                raise ValueError(
                    "affiliate_earning_id must be a positive integer"
                )

            if earning_id in seen:
                raise ValueError("duplicate affiliate earning allocation")

            seen.add(earning_id)
            normalized.append(
                (earning_id, cls._amount(line.amount))
            )

        return (
            event_id,
            tuple(sorted(normalized)),
            policy,
            namespace,
            request.source_event_key.strip(),
        )

    @staticmethod
    def _assert_settled_targets(cost, entries, rows):
        by_earning = {
            row.earning: row
            for row in rows
        }

        if len(by_earning) != len(entries):
            raise ValueError(
                "every allocation target must be an explicit settled earning"
            )

        for earning_id, _ in entries:
            lineage = by_earning.get(earning_id)

            if lineage is None:
                raise ValueError(
                    "every allocation target must be an explicit settled earning"
                )

            if lineage.currency != cost.currency:
                raise ValueError(
                    "allocation target currency does not match global cost currency"
                )

    def record(
        self,
        request: RecordGlobalCostAllocationRequest,
    ) -> GlobalCostAllocationRecord:
        (
            event_id,
            entries,
            policy,
            namespace,
            source_key,
        ) = self._normalized_request(request)

        digest = hashlib.sha256(
            source_key.encode("utf-8")
        ).hexdigest()

        cost = self.allocations.lock_cost_event(event_id)

        if cost is None:
            self.db.rollback()
            raise ValueError("affiliate cost event does not exist")

        fingerprint = canonical_fingerprint(
            "m10a9e-global-cost-allocation-v1",
            {
                "affiliate_cost_event_id": event_id,
                "affiliate_cost_event_fingerprint": cost.fingerprint,
                "allocations": [
                    {
                        "affiliate_earning_id": earning_id,
                        "amount": str(amount),
                    }
                    for earning_id, amount in entries
                ],
                "policy_version": policy,
                "source_namespace": namespace,
                "source_event_digest": digest,
            },
        )

        existing_source = self.allocations.batch_by_source(
            namespace,
            digest,
        )

        if existing_source is not None:
            return self._same_or_conflict(
                existing_source,
                fingerprint,
            )

        existing_cost = self.allocations.batch_by_cost_event(
            event_id
        )

        if existing_cost is not None:
            return self._same_or_conflict(
                existing_cost,
                fingerprint,
            )

        if cost.allocation_scope != "global":
            self.db.rollback()
            raise ValueError(
                "only global affiliate cost events may be allocated"
            )

        total = sum(
            (amount for _, amount in entries),
            Decimal("0.00"),
        )

        if total != Decimal(str(cost.amount)):
            self.db.rollback()
            raise ValueError(
                "allocation amounts must exactly equal the global cost amount"
            )

        try:
            rows = self.allocations.settled_earnings(
                earning_id
                for earning_id, _ in entries
            )
            self._assert_settled_targets(
                cost,
                entries,
                rows,
            )
        except Exception:
            self.db.rollback()
            raise

        batch = AffiliateGlobalCostAllocationBatch(
            affiliate_cost_event_id=event_id,
            allocated_amount=total,
            currency=cost.currency,
            policy_version=policy,
            source_namespace=namespace,
            source_event_digest=digest,
            fingerprint=fingerprint,
        )

        lines = [
            AffiliateGlobalCostAllocationLine(
                allocation_batch_id="",
                affiliate_earning_id=earning_id,
                amount=amount,
                fingerprint=canonical_fingerprint(
                    "m10a9e-global-cost-allocation-line-v1",
                    {
                        "batch_fingerprint": fingerprint,
                        "affiliate_earning_id": earning_id,
                        "amount": str(amount),
                    },
                ),
            )
            for earning_id, amount in entries
        ]

        try:
            self.allocations.add(batch, lines)
            self.db.commit()
            self.db.refresh(batch)

            return self._record(batch)

        except IntegrityError:
            self.db.rollback()

            existing = (
                self.allocations.batch_by_cost_event(event_id)
                or self.allocations.batch_by_source(
                    namespace,
                    digest,
                )
            )

            if existing is None:
                raise

            return self._same_or_conflict(
                existing,
                fingerprint,
            )

    def _same_or_conflict(self, existing, fingerprint):
        if existing.fingerprint != fingerprint:
            self.db.rollback()
            raise AffiliateGlobalCostAllocationConflict(
                "conflicting global-cost allocation replay"
            )

        record = self._record(existing)
        self.db.commit()
        return record

    def _record(self, batch):
        lines = self.allocations.lines_for_batch(batch.id)

        return GlobalCostAllocationRecord(
            batch.id,
            batch.affiliate_cost_event_id,
            Decimal(str(batch.allocated_amount)),
            batch.currency,
            batch.policy_version,
            batch.source_namespace,
            batch.source_event_digest,
            batch.fingerprint,
            tuple(
                GlobalCostAllocationLineRecord(
                    line.affiliate_earning_id,
                    Decimal(str(line.amount)),
                    line.fingerprint,
                )
                for line in lines
            ),
        )
