"""
Affiliate Links API

Creates, manages, and tracks affiliate links.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.database.session import SessionLocal

from app.services.affiliate_link_service import (
    AffiliateLinkService,
)

from app.services.affiliate_click_service import (
    AffiliateClickService,
)
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.services.attribution_link_bridge_service import (
    AttributionLinkBridgeService,
)
from app.services.attribution_redirect_bridge_service import (
    AttributionRedirectBridgeService,
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
    attribution_context_id: str | None = None,
    db: Session = Depends(get_db),
):

    if attribution_context_id is None:
        service = AffiliateLinkService(db)
        link = service.create_link(
            affiliate_program_id=affiliate_program_id,
            name=name,
            destination_url=destination_url,
            content_asset_id=content_asset_id,
        )
    else:
        try:
            bridge = AttributionLinkBridgeService(db)
            link = bridge.create_bound_link(
                affiliate_program_id=affiliate_program_id,
                attribution_context_id=attribution_context_id,
                name=name,
                destination_url=destination_url,
                content_asset_id=content_asset_id,
            )
        except AttributionBridgeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return {
        "success": True,
        "id": link.id,
        "tracking_code": link.tracking_code,
        "destination_url": link.destination_url,
    }


@router.post("/{link_id}/attribution-context/{context_id}")
def bind_affiliate_link_attribution_context(
    link_id: int,
    context_id: str,
    db: Session = Depends(get_db),
):
    try:
        link, _fact = AttributionLinkBridgeService(db).bind_existing(
            affiliate_link_id=link_id,
            attribution_context_id=context_id,
        )
        return {
            "success": True,
            "id": link.id,
            "tracking_code": link.tracking_code,
            "destination_url": link.destination_url,
        }
    except AttributionBridgeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
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

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if link.attribution_context_id is None:
        click_service = AffiliateClickService(db)
        click_service.record_click(
            tracking_code=tracking_code,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    else:
        try:
            AttributionRedirectBridgeService(db).record(
                tracking_code=tracking_code,
                event_id=idempotency_key,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except AttributionBridgeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return RedirectResponse(
        url=link.destination_url,
        status_code=307,
    )
