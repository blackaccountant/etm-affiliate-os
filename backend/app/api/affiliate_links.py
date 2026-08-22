"""
Affiliate Links API

Creates, manages, and tracks affiliate links.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.database.session import SessionLocal

from app.services.affiliate_link_service import (
    AffiliateLinkService,
)

from app.services.affiliate_click_service import (
    AffiliateClickService,
)


router = APIRouter(
    prefix="/affiliate-links",
    tags=["Affiliate Links"]
)


def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


@router.post("/create")
def create_affiliate_link(
    affiliate_program_id: int,
    name: str,
    destination_url: str,
    content_asset_id: int | None = None,
    db: Session = Depends(get_db),
):

    service = AffiliateLinkService(db)

    link = service.create_link(
        affiliate_program_id=affiliate_program_id,
        name=name,
        destination_url=destination_url,
        content_asset_id=content_asset_id,
    )

    return {
        "success": True,
        "id": link.id,
        "tracking_code": link.tracking_code,
        "destination_url": link.destination_url,
    }


@router.get("/{tracking_code}")
def get_affiliate_link(
    tracking_code: str,
    db: Session = Depends(get_db),
):

    service = AffiliateLinkService(db)

    link = service.get_by_tracking_code(
        tracking_code
    )

    if not link:

        return {
            "success": False,
            "message": "Link not found"
        }

    return {
        "success": True,
        "id": link.id,
        "destination_url": link.destination_url,
        "active": link.is_active,
    }


@router.get("/go/{tracking_code}")
def track_and_redirect(
    tracking_code: str,
    request: Request,
    db: Session = Depends(get_db),
):

    link_service = AffiliateLinkService(db)

    link = link_service.get_by_tracking_code(
        tracking_code
    )

    if not link:

        return {
            "success": False,
            "message": "Affiliate link not found"
        }

    if not link.is_active:

        return {
            "success": False,
            "message": "Affiliate link is inactive"
        }

    click_service = AffiliateClickService(db)

    click_service.record_click(
        tracking_code=tracking_code,
        ip_address=(
            request.client.host
            if request.client
            else None
        ),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    return RedirectResponse(
        url=link.destination_url,
        status_code=307,
    )