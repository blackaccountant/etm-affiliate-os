"""
Affiliate Conversion API

Records affiliate conversions and creates earnings.
"""

import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.services.affiliate_conversion_service import (
    AffiliateConversionService,
)


router = APIRouter(
    prefix="/affiliate-conversions",
    tags=["Affiliate Conversions"],
)


def get_db():

    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


class ConversionCreateRequest(BaseModel):

    affiliate_program_id: int

    sale_amount: Decimal

    currency: str = "USD"

    affiliate_link_id: Optional[int] = None

    tracking_code: Optional[str] = None

    external_conversion_id: Optional[str] = None

    customer_reference: Optional[str] = None

    conversion_status: str = "approved"

    commission_rate: Optional[Decimal] = None

    source: str = "api"

    metadata: Optional[dict] = None


@router.post("/create")
def create_conversion(
    payload: ConversionCreateRequest,
    db: Session = Depends(get_db),
):

    service = AffiliateConversionService(db)

    try:

        metadata_json = (
            json.dumps(payload.metadata)
            if payload.metadata is not None
            else None
        )

        conversion = service.create_conversion(
            affiliate_program_id=payload.affiliate_program_id,
            sale_amount=payload.sale_amount,
            currency=payload.currency,
            affiliate_link_id=payload.affiliate_link_id,
            tracking_code=payload.tracking_code,
            external_conversion_id=payload.external_conversion_id,
            customer_reference=payload.customer_reference,
            conversion_status=payload.conversion_status,
            commission_rate=payload.commission_rate,
            source=payload.source,
            metadata_json=metadata_json,
        )

        return {
            "success": True,
            "conversion_id": conversion.id,
            "affiliate_program_id": conversion.affiliate_program_id,
            "affiliate_link_id": conversion.affiliate_link_id,
            "sale_amount": str(conversion.sale_amount),
            "currency": conversion.currency,
            "conversion_status": conversion.conversion_status,
            "commission_rate": str(
                conversion.commission_rate
            ),
            "commission_amount": str(
                conversion.commission_amount
            ),
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except Exception as exc:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@router.get("/")
def list_conversions(
    limit: int = 100,
    db: Session = Depends(get_db),
):

    service = AffiliateConversionService(db)

    rows = service.list_conversions(limit)

    return {
        "success": True,
        "count": len(rows),
        "conversions": [
            {
                "id": row.id,
                "affiliate_program_id": row.affiliate_program_id,
                "affiliate_link_id": row.affiliate_link_id,
                "external_conversion_id":
                    row.external_conversion_id,
                "sale_amount": str(row.sale_amount),
                "currency": row.currency,
                "conversion_status":
                    row.conversion_status,
                "commission_rate":
                    str(row.commission_rate),
                "commission_amount":
                    str(row.commission_amount),
                "source": row.source,
                "created_at":
                    row.created_at.isoformat()
                    if row.created_at
                    else None,
            }
            for row in rows
        ],
    }


@router.get("/{conversion_id}")
def get_conversion(
    conversion_id: int,
    db: Session = Depends(get_db),
):

    service = AffiliateConversionService(db)

    conversion = service.get_conversion(
        conversion_id
    )

    if not conversion:

        raise HTTPException(
            status_code=404,
            detail="Conversion not found",
        )

    return {
        "success": True,
        "conversion": {
            "id": conversion.id,
            "affiliate_program_id":
                conversion.affiliate_program_id,
            "affiliate_link_id":
                conversion.affiliate_link_id,
            "external_conversion_id":
                conversion.external_conversion_id,
            "sale_amount":
                str(conversion.sale_amount),
            "currency":
                conversion.currency,
            "conversion_status":
                conversion.conversion_status,
            "commission_rate":
                str(conversion.commission_rate),
            "commission_amount":
                str(conversion.commission_amount),
            "source":
                conversion.source,
        },
    }