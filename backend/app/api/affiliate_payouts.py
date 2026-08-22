"""
Affiliate Payout API

Handles settlement of affiliate earnings into payouts.
"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.services.affiliate_payout_service import (
    AffiliatePayoutService,
)


router = APIRouter(
    prefix="/affiliate-payouts",
    tags=["Affiliate Payouts"],
)


# =========================================================
# Database dependency
# =========================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# =========================================================
# Request models
# =========================================================

class PayoutCreateRequest(BaseModel):
    affiliate_program_id: int
    currency: str = "USD"
    payout_reference: Optional[str] = None


class PayoutCompleteRequest(BaseModel):
    payout_reference: Optional[str] = None


# =========================================================
# Serialization
# =========================================================

def serialize_payout(payout):
    return {
        "id": payout.id,
        "affiliate_program_id": payout.affiliate_program_id,
        "total_amount": str(
            Decimal(str(payout.total_amount))
        ),
        "currency": payout.currency,
        "status": payout.status,
        "payout_reference": payout.payout_reference,
        "paid_at": (
            payout.paid_at.isoformat()
            if payout.paid_at
            else None
        ),
        "created_at": (
            payout.created_at.isoformat()
            if payout.created_at
            else None
        ),
        "updated_at": (
            payout.updated_at.isoformat()
            if payout.updated_at
            else None
        ),
    }


def serialize_payout_attempt(attempt):
    return {
        "id": attempt.id,
        "payout_id": attempt.payout_id,
        "attempt_number": attempt.attempt_number,
        "amount": str(
            Decimal(str(attempt.amount))
        ),
        "currency": attempt.currency,
        "status": attempt.status,
        "provider": attempt.provider,
        "provider_reference": attempt.provider_reference,
        "idempotency_key": attempt.idempotency_key,
        "failure_reason": attempt.failure_reason,
        "started_at": (
            attempt.started_at.isoformat()
            if attempt.started_at
            else None
        ),
        "completed_at": (
            attempt.completed_at.isoformat()
            if attempt.completed_at
            else None
        ),
        "created_at": (
            attempt.created_at.isoformat()
            if attempt.created_at
            else None
        ),
        "updated_at": (
            attempt.updated_at.isoformat()
            if attempt.updated_at
            else None
        ),
    }


# =========================================================
# Create payout
# =========================================================

@router.post("/create")
def create_payout(
    payload: PayoutCreateRequest,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    try:
        payout = service.create_payout(
            affiliate_program_id=payload.affiliate_program_id,
            currency=payload.currency,
            payout_reference=payload.payout_reference,
        )

        return {
            "success": True,
            "message": "Affiliate payout created",
            "payout": serialize_payout(payout),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# List payouts
# =========================================================

@router.get("/")
def list_payouts(
    limit: int = 100,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    payouts = service.list_payouts(
        limit=limit
    )

    return {
        "success": True,
        "count": len(payouts),
        "payouts": [
            serialize_payout(payout)
            for payout in payouts
        ],
    }


# =========================================================
# Get payout
# =========================================================

@router.get("/{payout_id}")
def get_payout(
    payout_id: int,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    payout = service.get_payout(
        payout_id
    )

    if not payout:
        raise HTTPException(
            status_code=404,
            detail="Affiliate payout not found",
        )

    return {
        "success": True,
        "payout": serialize_payout(payout),
    }


# =========================================================
# List attempts
# =========================================================

@router.get("/{payout_id}/attempts")
def list_payout_attempts(
    payout_id: int,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    payout = service.get_payout(
        payout_id
    )

    if not payout:
        raise HTTPException(
            status_code=404,
            detail="Affiliate payout not found",
        )

    attempts = service.list_payout_attempts(
        payout_id
    )

    return {
        "success": True,
        "payout_id": payout_id,
        "count": len(attempts),
        "attempts": [
            serialize_payout_attempt(attempt)
            for attempt in attempts
        ],
    }


# =========================================================
# Process payout
# =========================================================

@router.post("/{payout_id}/process")
def process_payout(
    payout_id: int,
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    try:
        payout = service.process_payout(
            payout_id=payout_id,
            provider="manual",
            idempotency_key=idempotency_key,
        )

        return {
            "success": True,
            "message": "Affiliate payout is now processing",
            "payout": serialize_payout(payout),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# Complete payout
# =========================================================

@router.post("/{payout_id}/complete")
def complete_payout(
    payout_id: int,
    payload: PayoutCompleteRequest,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    try:
        payout = service.complete_payout(
            payout_id=payout_id,
            payout_reference=payload.payout_reference,
        )

        return {
            "success": True,
            "message": "Affiliate payout completed",
            "payout": serialize_payout(payout),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# Fail payout
# =========================================================

@router.post("/{payout_id}/fail")
def fail_payout(
    payout_id: int,
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    try:
        payout = service.fail_payout(
            payout_id
        )

        return {
            "success": True,
            "message": "Affiliate payout marked as failed",
            "payout": serialize_payout(payout),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# =========================================================
# Retry payout
# =========================================================

@router.post("/{payout_id}/retry")
def retry_payout(
    payout_id: int,
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    db: Session = Depends(get_db),
):
    service = AffiliatePayoutService(db)

    try:
        payout = service.retry_payout(
            payout_id=payout_id,
            provider="manual",
            idempotency_key=idempotency_key,
        )

        return {
            "success": True,
            "message": "Affiliate payout retry started",
            "payout": serialize_payout(payout),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )