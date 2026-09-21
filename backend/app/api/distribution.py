"""Authenticated operational API for pre-publication Pilot 1 launch binding."""

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.operator_auth import require_operator_api_key
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.database.session import SessionLocal
from app.models.distribution_run import DistributionRun
from app.distribution.pilot_revenue_launch_contracts import PilotRevenueLaunchRequest
from app.services.content_distribution_mission_launch_service import ContentDistributionMissionLaunchService
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

    try:
        result = ContentDistributionMissionLaunchService(session_factory=SessionLocal).launch(run.id)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"distribution_run_id": result.distribution_run_id, "mission_id": result.mission_id, "mission_status": result.mission_status, "workflow": result.workflow}
