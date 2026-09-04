"""Read-only query repository for UIF5E immutable attribution lineage."""

from sqlalchemy.orm import Session

from app.models.attribution import (
    AttributionClick,
    AttributionContext,
    AttributionFact,
    AttributionPublication,
)
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink


class AttributionLineageVisibilityRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_publications(self, limit: int = 50):
        return (
            self.db.query(AttributionPublication)
            .order_by(AttributionPublication.created_at.desc(), AttributionPublication.id.desc())
            .limit(limit)
            .all()
        )

    def list_contexts(self, limit: int = 50):
        return (
            self.db.query(AttributionContext)
            .order_by(AttributionContext.created_at.desc(), AttributionContext.id.desc())
            .limit(limit)
            .all()
        )

    def list_clicks(self, limit: int = 50):
        return (
            self.db.query(AttributionClick)
            .order_by(AttributionClick.recorded_at.desc(), AttributionClick.id.desc())
            .limit(limit)
            .all()
        )

    def list_facts(self, limit: int = 50):
        return (
            self.db.query(AttributionFact)
            .order_by(AttributionFact.recorded_at.desc(), AttributionFact.id.desc())
            .limit(limit)
            .all()
        )

    def list_earning_links(self, limit: int = 50):
        return (
            self.db.query(AttributionEarningLink)
            .order_by(AttributionEarningLink.recorded_at.desc(), AttributionEarningLink.id.desc())
            .limit(limit)
            .all()
        )

    def list_settlement_links(self, limit: int = 50):
        return (
            self.db.query(AttributionPayoutSettlementLink)
            .order_by(
                AttributionPayoutSettlementLink.recorded_at.desc(),
                AttributionPayoutSettlementLink.id.desc(),
            )
            .limit(limit)
            .all()
        )
