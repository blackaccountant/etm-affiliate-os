"""PostgreSQL-safe persistence primitives for M10A4 earning linkage."""

from sqlalchemy import text

from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.attribution import AttributionFact
from app.models.attribution_earning_link import AttributionEarningLink


class AttributionEarningLinkRepository:
    def __init__(self, db):
        self.db = db

    def acquire_conversion_lock(self, conversion_id: int) -> None:
        if self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
                {"identity": f"m10a4.earning-link:{conversion_id}"},
            )

    def lock_fact(self, fact_id: str):
        return (
            self.db.query(AttributionFact)
            .filter(AttributionFact.id == fact_id)
            .with_for_update()
            .one_or_none()
        )

    def lock_conversion(self, conversion_id: int):
        return (
            self.db.query(AffiliateConversion)
            .filter(AffiliateConversion.id == conversion_id)
            .with_for_update()
            .one_or_none()
        )

    def lock_earnings_for_conversion(self, conversion_id: int):
        return (
            self.db.query(AffiliateEarning)
            .filter(AffiliateEarning.conversion_id == conversion_id)
            .with_for_update()
            .all()
        )

    def by_fact(self, fact_id: str):
        return self.db.query(AttributionEarningLink).filter_by(attribution_fact_id=fact_id).one_or_none()

    def by_conversion(self, conversion_id: int):
        return self.db.query(AttributionEarningLink).filter_by(affiliate_conversion_id=conversion_id).one_or_none()

    def by_earning(self, earning_id: int):
        return self.db.query(AttributionEarningLink).filter_by(affiliate_earning_id=earning_id).one_or_none()

    def create(self, link: AttributionEarningLink):
        self.db.add(link)
        self.db.flush()
        return link
