"""Read-only HTTP surface for frozen M10 economic performance projection."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.economic_performance_schemas import EconomicPerformanceResponse
from app.attribution.operating_profit_projection_contracts import (
    OperatingProfitProjectionRequest,
)
from app.dependencies import get_db
from app.services.attribution_operating_profit_projection_service import (
    AttributionOperatingProfitProjectionService,
)


router = APIRouter(prefix="/economics", tags=["Economics"])


@router.get("/performance", response_model=EconomicPerformanceResponse)
def get_economic_performance(db: Session = Depends(get_db)):
    """Project frozen M10 operating-profit truth at native-currency aggregate grain."""
    try:
        rows = AttributionOperatingProfitProjectionService(db).project(
            OperatingProfitProjectionRequest()
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"economic projection authority conflict: {exc}",
        ) from exc

    return {"rows": rows}
