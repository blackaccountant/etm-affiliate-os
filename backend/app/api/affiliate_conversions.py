"""
Affiliate Conversion API

Records affiliate conversions and creates earnings.
"""

import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.operator_auth import require_operator_api_key
from app.database.session import SessionLocal
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.models.affiliate_link import AffiliateLink
from app.services.affiliate_conversion_service import (
    AffiliateConversionService,
)
from app.services.attribution_conversion_bridge_service import (
    AttributionConversionBridgeService,
)
from app.services.cj_commission_client import CjCommissionClientError
from app.services.cj_financial_ingestion_service import CjFinancialIngestionService


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

    attribution_click_key: Optional[str] = None


class CjCommissionSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_run_id: str
    advertiser_id: str
    since_posting_date: datetime
    before_posting_date: datetime


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

        link = None
        if payload.affiliate_link_id is not None:
            link = db.get(AffiliateLink, payload.affiliate_link_id)
        elif payload.tracking_code:
            link = (
                db.query(AffiliateLink)
                .filter(AffiliateLink.tracking_code == payload.tracking_code)
                .first()
            )

        if link is not None and link.attribution_context_id is not None:
            bridge_result = AttributionConversionBridgeService(db).record(
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
                attribution_click_key=payload.attribution_click_key,
            )
            conversion = bridge_result["conversion"]
        else:
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

    except AttributionBridgeConflict as exc:

        raise HTTPException(
            status_code=409,
            detail=str(exc),
        )

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


@router.post("/cj/sync", dependencies=[Depends(require_operator_api_key)])
def sync_cj_commissions(
    payload: CjCommissionSyncRequest,
    db: Session = Depends(get_db),
):
    try:
        return CjFinancialIngestionService(db).sync(
            distribution_run_id=payload.distribution_run_id,
            advertiser_id=payload.advertiser_id,
            since_posting_date=payload.since_posting_date,
            before_posting_date=payload.before_posting_date,
        )
    except AttributionBridgeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CjCommissionClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
