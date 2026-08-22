"""
Affiliate Earnings API

Provides reporting and payout management for affiliate earnings.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.affiliate_earning import AffiliateEarning


router = APIRouter(
    prefix="/affiliate-earnings",
    tags=["Affiliate Earnings"],
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# =========================================================
# REQUEST MODELS
# =========================================================

class MarkPaidRequest(BaseModel):
    payout_reference: str


# =========================================================
# LIST EARNINGS
# =========================================================

@router.get("/")
def list_earnings(
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    List affiliate earnings.

    Optional status filter:
        pending
        approved
        paid
        rejected
    """

    query = db.query(AffiliateEarning)

    if status:
        query = query.filter(
            AffiliateEarning.status == status
        )

    rows = (
        query
        .order_by(AffiliateEarning.id.desc())
        .limit(limit)
        .all()
    )

    return {
        "success": True,
        "count": len(rows),
        "earnings": [
            {
                "id": row.id,
                "conversion_id": row.conversion_id,
                "affiliate_program_id": row.affiliate_program_id,
                "gross_amount": str(row.gross_amount),
                "commission_rate": (
                    str(row.commission_rate)
                    if row.commission_rate is not None
                    else None
                ),
                "commission_amount": str(
                    row.commission_amount
                ),
                "currency": row.currency,
                "status": row.status,
                "payout_reference": row.payout_reference,
                "paid_at": (
                    row.paid_at.isoformat()
                    if row.paid_at
                    else None
                ),
                "created_at": (
                    row.created_at.isoformat()
                    if row.created_at
                    else None
                ),
            }
            for row in rows
        ],
    }


# =========================================================
# GET SINGLE EARNING
# =========================================================

@router.get("/{earning_id}")
def get_earning(
    earning_id: int,
    db: Session = Depends(get_db),
):
    """
    Get one affiliate earning.
    """

    earning = (
        db.query(AffiliateEarning)
        .filter(
            AffiliateEarning.id == earning_id
        )
        .first()
    )

    if not earning:
        raise HTTPException(
            status_code=404,
            detail="Affiliate earning not found",
        )

    return {
        "success": True,
        "earning": {
            "id": earning.id,
            "conversion_id": earning.conversion_id,
            "affiliate_program_id":
                earning.affiliate_program_id,
            "gross_amount": str(
                earning.gross_amount
            ),
            "commission_rate": (
                str(earning.commission_rate)
                if earning.commission_rate is not None
                else None
            ),
            "commission_amount": str(
                earning.commission_amount
            ),
            "currency": earning.currency,
            "status": earning.status,
            "payout_reference":
                earning.payout_reference,
            "paid_at": (
                earning.paid_at.isoformat()
                if earning.paid_at
                else None
            ),
            "created_at": (
                earning.created_at.isoformat()
                if earning.created_at
                else None
            ),
        },
    }


# =========================================================
# EARNINGS SUMMARY
# =========================================================

@router.get("/summary/overview")
def earnings_summary(
    db: Session = Depends(get_db),
):
    """
    Return aggregate affiliate earnings.
    """

    rows = (
        db.query(AffiliateEarning)
        .all()
    )

    total_gross = Decimal("0")
    total_commission = Decimal("0")

    pending_amount = Decimal("0")
    approved_amount = Decimal("0")
    paid_amount = Decimal("0")
    rejected_amount = Decimal("0")

    pending_count = 0
    approved_count = 0
    paid_count = 0
    rejected_count = 0

    for row in rows:

        gross = Decimal(
            str(row.gross_amount or 0)
        )

        commission = Decimal(
            str(row.commission_amount or 0)
        )

        total_gross += gross
        total_commission += commission

        status = (
            row.status or ""
        ).lower()

        if status == "pending":

            pending_amount += commission
            pending_count += 1

        elif status == "approved":

            approved_amount += commission
            approved_count += 1

        elif status == "paid":

            paid_amount += commission
            paid_count += 1

        elif status == "rejected":

            rejected_amount += commission
            rejected_count += 1

    return {
        "success": True,

        "total_earnings": len(rows),

        "total_gross_amount": str(
            total_gross
        ),

        "total_commission_amount": str(
            total_commission
        ),

        "pending": {
            "count": pending_count,
            "amount": str(
                pending_amount
            ),
        },

        "approved": {
            "count": approved_count,
            "amount": str(
                approved_amount
            ),
        },

        "paid": {
            "count": paid_count,
            "amount": str(
                paid_amount
            ),
        },

        "rejected": {
            "count": rejected_count,
            "amount": str(
                rejected_amount
            ),
        },
    }


# =========================================================
# MARK EARNING AS PAID
# =========================================================

@router.post("/{earning_id}/pay")
def mark_earning_paid(
    earning_id: int,
    payload: MarkPaidRequest,
    db: Session = Depends(get_db),
):
    """
    Mark an affiliate earning as paid.
    """

    earning = (
        db.query(AffiliateEarning)
        .filter(
            AffiliateEarning.id == earning_id
        )
        .first()
    )

    if not earning:

        raise HTTPException(
            status_code=404,
            detail="Affiliate earning not found",
        )

    # -----------------------------------------------------
    # Prevent duplicate payment
    # -----------------------------------------------------

    if earning.status == "paid":

        raise HTTPException(
            status_code=409,
            detail="Affiliate earning has already been paid",
        )

    # -----------------------------------------------------
    # Validate payout reference
    # -----------------------------------------------------

    payout_reference = (
        payload.payout_reference.strip()
    )

    if not payout_reference:

        raise HTTPException(
            status_code=400,
            detail="Payout reference is required",
        )

    # -----------------------------------------------------
    # Update earning
    # -----------------------------------------------------

    earning.status = "paid"

    earning.payout_reference = (
        payout_reference
    )

    earning.paid_at = datetime.utcnow()

    earning.updated_at = datetime.utcnow()

    db.commit()

    db.refresh(earning)

    return {
        "success": True,
        "message": "Affiliate earning marked as paid",
        "earning": {
            "id": earning.id,
            "conversion_id":
                earning.conversion_id,
            "affiliate_program_id":
                earning.affiliate_program_id,
            "commission_amount":
                str(earning.commission_amount),
            "currency":
                earning.currency,
            "status":
                earning.status,
            "payout_reference":
                earning.payout_reference,
            "paid_at":
                earning.paid_at.isoformat()
                if earning.paid_at
                else None,
        },
    }