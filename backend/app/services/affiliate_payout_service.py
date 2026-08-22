"""
Affiliate Payout Service

Handles settlement of affiliate earnings into payouts.

Workflow:

approved earning
    ↓
create payout
    ↓
earning.payout_id = payout.id
    ↓
payout processing
    ↓
payout attempt created
    ↓
payout completed OR failed
    ↓
retry if failed
    ↓
new payout attempt
    ↓
payout completed
    ↓
attempt completed
    ↓
earning status = paid
    ↓
payout status = paid

Production hardening:
- Every newly created payout attempt gets a unique idempotency key.
- Every attempt has a provider field.
- Provider references are stored at attempt level.
- Existing attempts remain immutable audit records once completed/failed.
- A payout may only have one processing attempt.
- Processing/retry decisions lock the payout row with PostgreSQL FOR UPDATE.
- The payout row is the serialization point for concurrent processing requests.
- Paid payouts cannot be processed, failed, retried, or completed again.
- Reusing an idempotency key for the same payout is safe.
- Reusing an idempotency key for another payout is rejected.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram


class AffiliatePayoutService:

    def __init__(self, db: Session):
        self.db = db

    # =========================================================
    # Create payout
    # =========================================================

    def create_payout(
        self,
        affiliate_program_id: int,
        currency: str = "USD",
        payout_reference: Optional[str] = None,
    ):
        program = (
            self.db.query(AffiliateProgram)
            .filter(
                AffiliateProgram.id == affiliate_program_id
            )
            .first()
        )

        if not program:
            raise ValueError(
                "Affiliate program not found"
            )

        earnings = (
            self.db.query(AffiliateEarning)
            .filter(
                AffiliateEarning.affiliate_program_id
                == affiliate_program_id,
                AffiliateEarning.status == "approved",
                AffiliateEarning.currency == currency,
                AffiliateEarning.payout_id.is_(None),
            )
            .all()
        )

        if not earnings:
            raise ValueError(
                "No approved earnings available for payout"
            )

        total_amount = sum(
            (
                Decimal(str(e.commission_amount))
                for e in earnings
            ),
            Decimal("0"),
        )

        if total_amount <= 0:
            raise ValueError(
                "Payout amount must be greater than zero"
            )

        now = datetime.utcnow()

        payout = AffiliatePayout(
            affiliate_program_id=affiliate_program_id,
            total_amount=total_amount,
            currency=currency,
            status="pending",
            payout_reference=payout_reference,
            paid_at=None,
            created_at=now,
            updated_at=now,
        )

        self.db.add(payout)
        self.db.flush()

        for earning in earnings:
            earning.payout_id = payout.id
            earning.updated_at = now

        self.db.commit()
        self.db.refresh(payout)

        return payout

    # =========================================================
    # Get payout
    # =========================================================

    def get_payout(
        self,
        payout_id: int,
    ):
        return (
            self.db.query(AffiliatePayout)
            .filter(
                AffiliatePayout.id == payout_id
            )
            .first()
        )

    # =========================================================
    # Get payout with row-level lock
    # =========================================================
    #
    # PostgreSQL FOR UPDATE is critical here.
    #
    # Without the lock, two concurrent requests can both read
    # a payout as "pending" before either request commits. Both
    # can then create attempt_number=1.
    #
    # The payout row is the serialization point: only one
    # transaction can make a processing decision for a payout
    # at a time.
    #
    def get_payout_for_update(
        self,
        payout_id: int,
    ):
        return (
            self.db.query(AffiliatePayout)
            .filter(
                AffiliatePayout.id == payout_id
            )
            .with_for_update()
            .first()
        )

    # =========================================================
    # List payout attempts
    # =========================================================

    def list_payout_attempts(
        self,
        payout_id: int,
    ):
        return (
            self.db.query(AffiliatePayoutAttempt)
            .filter(
                AffiliatePayoutAttempt.payout_id == payout_id
            )
            .order_by(
                AffiliatePayoutAttempt.attempt_number.asc()
            )
            .all()
        )

    # =========================================================
    # Get current processing attempt
    # =========================================================

    def get_processing_attempt(
        self,
        payout_id: int,
    ):
        return (
            self.db.query(AffiliatePayoutAttempt)
            .filter(
                AffiliatePayoutAttempt.payout_id == payout_id,
                AffiliatePayoutAttempt.status == "processing",
            )
            .order_by(
                AffiliatePayoutAttempt.attempt_number.desc()
            )
            .first()
        )

    # =========================================================
    # Generate idempotency key
    # =========================================================

    def generate_idempotency_key(
        self,
        payout_id: int,
        attempt_number: int,
    ) -> str:
        return (
            f"payout:{payout_id}:"
            f"attempt:{attempt_number}:"
            f"{uuid4().hex}"
        )

    # =========================================================
    # Resolve / validate idempotency key
    # =========================================================

    def resolve_idempotency_key(
        self,
        payout: AffiliatePayout,
        attempt_number: int,
        idempotency_key: Optional[str] = None,
    ) -> str:

        if idempotency_key:
            existing_key_attempt = (
                self.db.query(AffiliatePayoutAttempt)
                .filter(
                    AffiliatePayoutAttempt.idempotency_key
                    == idempotency_key
                )
                .first()
            )

            if existing_key_attempt:
                if existing_key_attempt.payout_id != payout.id:
                    raise ValueError(
                        "Idempotency key is already associated with another payout"
                    )

                return existing_key_attempt.idempotency_key

            return idempotency_key

        return self.generate_idempotency_key(
            payout_id=payout.id,
            attempt_number=attempt_number,
        )

    # =========================================================
    # Create payout attempt
    # =========================================================

    def create_payout_attempt(
        self,
        payout: AffiliatePayout,
        provider: str = "manual",
        idempotency_key: Optional[str] = None,
    ):
        existing_processing_attempt = (
            self.get_processing_attempt(payout.id)
        )

        if existing_processing_attempt:

            if (
                idempotency_key
                and existing_processing_attempt.idempotency_key
                == idempotency_key
            ):
                return existing_processing_attempt

            raise ValueError(
                "Affiliate payout already has a processing attempt"
            )

        latest_attempt = (
            self.db.query(AffiliatePayoutAttempt)
            .filter(
                AffiliatePayoutAttempt.payout_id
                == payout.id
            )
            .order_by(
                AffiliatePayoutAttempt.attempt_number.desc()
            )
            .first()
        )

        attempt_number = (
            latest_attempt.attempt_number + 1
            if latest_attempt
            else 1
        )

        resolved_idempotency_key = (
            self.resolve_idempotency_key(
                payout=payout,
                attempt_number=attempt_number,
                idempotency_key=idempotency_key,
            )
        )

        existing_key_attempt = (
            self.db.query(AffiliatePayoutAttempt)
            .filter(
                AffiliatePayoutAttempt.idempotency_key
                == resolved_idempotency_key
            )
            .first()
        )

        if existing_key_attempt:

            if existing_key_attempt.payout_id != payout.id:
                raise ValueError(
                    "Idempotency key is already associated with another payout"
                )

            return existing_key_attempt

        now = datetime.utcnow()

        attempt = AffiliatePayoutAttempt(
            payout_id=payout.id,
            attempt_number=attempt_number,
            amount=payout.total_amount,
            currency=payout.currency,
            status="processing",
            provider=provider,
            provider_reference=None,
            idempotency_key=resolved_idempotency_key,
            failure_reason=None,
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )

        self.db.add(attempt)
        self.db.flush()

        return attempt

    # =========================================================
    # List payouts
    # =========================================================

    def list_payouts(
        self,
        limit: int = 100,
    ):
        return (
            self.db.query(AffiliatePayout)
            .order_by(
                AffiliatePayout.id.desc()
            )
            .limit(limit)
            .all()
        )

    # =========================================================
    # Process payout
    # =========================================================

    def process_payout(
        self,
        payout_id: int,
        provider: str = "manual",
        idempotency_key: Optional[str] = None,
    ):
        payout = self.get_payout_for_update(payout_id)

        if not payout:
            self.db.rollback()
            raise ValueError(
                "Affiliate payout not found"
            )

        if payout.status == "paid":
            self.db.rollback()
            raise ValueError(
                "Affiliate payout has already been paid"
            )

        if payout.status == "processing":

            existing_attempt = self.get_processing_attempt(
                payout.id
            )

            if existing_attempt:

                if (
                    idempotency_key
                    and existing_attempt.idempotency_key
                    == idempotency_key
                ):
                    return payout

                self.db.rollback()
                raise ValueError(
                    "Affiliate payout is already processing"
                )

            self.db.rollback()
            raise ValueError(
                "Affiliate payout is processing without an active attempt"
            )

        if payout.status == "failed":
            self.db.rollback()
            raise ValueError(
                "Failed payout must be reviewed before processing"
            )

        if payout.status != "pending":
            self.db.rollback()
            raise ValueError(
                "Affiliate payout cannot be processed"
            )

        now = datetime.utcnow()

        payout.status = "processing"
        payout.updated_at = now

        try:

            self.create_payout_attempt(
                payout=payout,
                provider=provider,
                idempotency_key=idempotency_key,
            )

            self.db.commit()
            self.db.refresh(payout)

        except IntegrityError:

            self.db.rollback()

            raise ValueError(
                "Duplicate payout attempt or idempotency key"
            )

        except Exception:

            self.db.rollback()
            raise

        return payout

    # =========================================================
    # Complete payout
    # =========================================================

    def complete_payout(
        self,
        payout_id: int,
        payout_reference: Optional[str] = None,
    ):
        payout = self.get_payout(payout_id)

        if not payout:
            raise ValueError(
                "Affiliate payout not found"
            )

        if payout.status == "paid":
            raise ValueError(
                "Affiliate payout has already been paid"
            )

        if payout.status != "processing":
            raise ValueError(
                "Affiliate payout must be processing before completion"
            )

        earnings = (
            self.db.query(AffiliateEarning)
            .filter(
                AffiliateEarning.payout_id == payout.id
            )
            .all()
        )

        if not earnings:
            raise ValueError(
                "No earnings are attached to this payout"
            )

        current_attempt = self.get_processing_attempt(
            payout.id
        )

        if not current_attempt:
            raise ValueError(
                "No processing payout attempt found"
            )

        paid_at = datetime.utcnow()

        try:

            for earning in earnings:

                if earning.status != "paid":
                    earning.status = "paid"
                    earning.paid_at = paid_at
                    earning.updated_at = paid_at

                if payout_reference:
                    earning.payout_reference = payout_reference

            current_attempt.status = "completed"
            current_attempt.completed_at = paid_at
            current_attempt.updated_at = paid_at

            if payout_reference:
                current_attempt.provider_reference = (
                    payout_reference
                )

            if payout_reference:
                payout.payout_reference = payout_reference

            payout.status = "paid"
            payout.paid_at = paid_at
            payout.updated_at = paid_at

            self.db.commit()
            self.db.refresh(payout)

        except Exception:

            self.db.rollback()
            raise

        return payout

    # =========================================================
    # Fail payout
    # =========================================================

    def fail_payout(
        self,
        payout_id: int,
    ):
        payout = self.get_payout(payout_id)

        if not payout:
            raise ValueError(
                "Affiliate payout not found"
            )

        if payout.status == "paid":
            raise ValueError(
                "Paid payout cannot be marked as failed"
            )

        if payout.status == "failed":
            raise ValueError(
                "Affiliate payout is already failed"
            )

        if payout.status != "processing":
            raise ValueError(
                "Affiliate payout must be processing before it can fail"
            )

        current_attempt = self.get_processing_attempt(
            payout.id
        )

        if not current_attempt:
            raise ValueError(
                "No processing payout attempt found"
            )

        now = datetime.utcnow()

        try:

            payout.status = "failed"
            payout.updated_at = now

            current_attempt.status = "failed"
            current_attempt.completed_at = now
            current_attempt.updated_at = now
            current_attempt.failure_reason = (
                "Payout marked as failed"
            )

            self.db.commit()
            self.db.refresh(payout)

        except Exception:

            self.db.rollback()
            raise

        return payout

    # =========================================================
    # Retry payout
    # =========================================================

    def retry_payout(
        self,
        payout_id: int,
        provider: str = "manual",
        idempotency_key: Optional[str] = None,
    ):
        # Serialize retry decisions for this payout.
        payout = self.get_payout_for_update(payout_id)

        if not payout:
            self.db.rollback()
            raise ValueError(
                "Affiliate payout not found"
            )

        if payout.status == "paid":
            self.db.rollback()
            raise ValueError(
                "Paid payout cannot be retried"
            )

        if payout.status == "pending":
            self.db.rollback()
            raise ValueError(
                "Pending payout does not need retry"
            )

        if payout.status == "processing":

            existing_attempt = self.get_processing_attempt(
                payout.id
            )

            if existing_attempt:

                if (
                    idempotency_key
                    and existing_attempt.idempotency_key
                    == idempotency_key
                ):
                    return payout

                raise ValueError(
                    "Affiliate payout is already processing"
                )

            raise ValueError(
                "Affiliate payout is processing without an active attempt"
            )

        if payout.status != "failed":
            raise ValueError(
                "Only failed payouts can be retried"
            )

        now = datetime.utcnow()

        try:

            payout.status = "processing"
            payout.updated_at = now

            self.create_payout_attempt(
                payout=payout,
                provider=provider,
                idempotency_key=idempotency_key,
            )

            self.db.commit()
            self.db.refresh(payout)

        except IntegrityError:

            self.db.rollback()

            raise ValueError(
                "Duplicate payout attempt or idempotency key"
            )

        except Exception:

            self.db.rollback()
            raise

        return payout