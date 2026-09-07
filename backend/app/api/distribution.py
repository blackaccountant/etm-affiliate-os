"""Authenticated operational API for pre-publication Pilot 1 launch binding."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.operator_auth import require_operator_api_key
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.core.config import settings
from app.database.session import SessionLocal
from app.distribution.adapters.wordpress import WordPressDistributionAdapter, deterministic_wordpress_slug
from app.distribution.contracts import DistributionPublishRequest
from app.models.affiliate_link import AffiliateLink
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.distribution_run import DistributionRun
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.distribution.pilot_revenue_launch_contracts import PilotRevenueLaunchRequest
from app.services.pilot_revenue_launch_service import PilotRevenueLaunchService


router = APIRouter(prefix="/distribution", tags=["Distribution"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class PilotRevenueLaunchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    evaluation_id: str
    platform: str
    account_reference: str
    destination: str
    affiliate_link_id: int
    prepared_content_body: str | None = None
    scheduled_for: datetime | None = None


class PilotCmsPublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distribution_run_id: str


def _resolve_bound_tracking_code(db: Session, distribution_run_id: str) -> str:
    publication = db.query(AttributionPublication).filter_by(distribution_run_id=distribution_run_id).first()
    if publication is None:
        raise ValueError("distribution run is not bound to attribution lineage")
    context = db.query(AttributionContext).filter_by(attribution_publication_id=publication.id).first()
    if context is None:
        raise ValueError("distribution run attribution context is missing")
    link = db.query(AffiliateLink).filter_by(attribution_context_id=context.id).first()
    if link is None or not getattr(link, "tracking_code", None):
        raise ValueError("affiliate tracking code is unavailable")
    return str(link.tracking_code)


def _absolute_tracked_url(tracking_code: str) -> str:
    base = (settings.PUBLIC_API_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise ValueError("PUBLIC_API_BASE_URL is not configured")
    return f"{base}/affiliate-links/go/{tracking_code}"


def _render_final_content(prepared_content_body: str | None, tracked_url: str) -> str:
    source = (prepared_content_body or "").strip()
    placeholder_patterns = [
        r"\{\{\s*(?:affiliate|tracked)[^\n}]*?(?:link|url)\s*\}\}",
        r"\{\s*(?:affiliate|tracked)[^\n}]*?(?:link|url)\s*\}",
        r"<\s*affiliate-cta\s*>",
        r"<!--\s*affiliate-link\s*-->",
    ]
    for pattern in placeholder_patterns:
        rendered = re.sub(pattern, f'<p><a href="{tracked_url}">Learn more</a></p>', source, flags=re.IGNORECASE)
        if rendered != source:
            return rendered

    if not source:
        return f'<p><a href="{tracked_url}">Learn more</a></p>'
    if source.endswith("\n"):
        source = source.rstrip()
    return f"{source}\n\n<p><a href=\"{tracked_url}\">Learn more</a></p>"


@router.post("/pilot-launch", dependencies=[Depends(require_operator_api_key)])
def pilot_launch(payload: PilotRevenueLaunchPayload, db: Session = Depends(get_db)):
    try:
        result = PilotRevenueLaunchService(db).launch(PilotRevenueLaunchRequest(**payload.model_dump()))
        return {
            "distribution_run_id": result.distribution_run_id,
            "attribution_publication_id": result.attribution_publication_id,
            "attribution_context_id": result.attribution_context_id,
            "affiliate_link_id": result.affiliate_link_id,
            "tracking_code": result.tracking_code,
            "public_redirect_path": result.public_redirect_path,
        }
    except AttributionBridgeConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/pilot-cms-publish", dependencies=[Depends(require_operator_api_key)])
def pilot_cms_publish(payload: PilotCmsPublishPayload, db: Session = Depends(get_db)):
    run = db.get(DistributionRun, payload.distribution_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="distribution run does not exist")

    if run.status == "COMPLETED":
        return {
            "distribution_run_id": run.id,
            "status": run.status,
            "external_post_id": run.external_post_id,
            "external_url": run.external_url,
        }

    tracking_code = _resolve_bound_tracking_code(db, run.id)
    tracked_url = _absolute_tracked_url(tracking_code)
    final_body = _render_final_content(run.prepared_content_body, tracked_url)
    adapter = WordPressDistributionAdapter()
    publication = DistributionPublishRequest(
        distribution_run_id=run.id,
        generated_content_artifact_id=run.generated_content_artifact_id,
        content_evaluation_id=run.content_evaluation_id,
        platform=run.platform,
        account_reference=run.account_reference,
        destination=run.destination,
        payload_fingerprint=run.payload_fingerprint,
        content_body=final_body,
        scheduled_for=run.scheduled_for,
        correlation_key=f"distribution:{run.id}",
    )
    result = adapter.publish(publication)
    if result.success:
        run.status = "COMPLETED"
        run.external_post_id = result.external_post_id
        run.external_url = result.external_url
        run.result_metadata = result.safe_metadata
        run.completed_at = result.published_at
        run.failure_category = None
        run.error_summary = None
        run.updated_at = datetime.now().astimezone()
        db.commit()
        return {
            "distribution_run_id": run.id,
            "status": run.status,
            "external_post_id": result.external_post_id,
            "external_url": result.external_url,
        }

    run.status = "FAILED"
    run.failure_category = result.failure_category.value if result.failure_category is not None else "UNKNOWN_PERMANENT"
    run.error_summary = result.safe_message
    run.updated_at = datetime.now().astimezone()
    db.commit()
    raise HTTPException(status_code=502, detail=result.safe_message or "wordpress publish failed")
