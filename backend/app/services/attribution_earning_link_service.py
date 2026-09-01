"""Outer-transaction reconciliation of one conversion fact to one earning."""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.attribution.earning_linkage_contracts import (
    EARNING_LINK_SOURCE_NAMESPACE,
    AttributionEarningLinkConflict,
    earning_link_digest,
    earning_link_fingerprint,
)
from app.models.attribution_earning_link import AttributionEarningLink
from app.repositories.attribution_earning_link_repository import AttributionEarningLinkRepository


class AttributionEarningLinkService:
    def __init__(self, db):
        self.db = db
        self.links = AttributionEarningLinkRepository(db)

    @staticmethod
    def _assert_same(existing, *, fact_id: str, conversion_id: int, earning_id: int):
        if (
            existing.attribution_fact_id != fact_id
            or existing.affiliate_conversion_id != conversion_id
            or existing.affiliate_earning_id != earning_id
        ):
            raise AttributionEarningLinkConflict(
                "attribution earning linkage conflicts with authoritative identity"
            )

    def reconcile(self, *, attribution_fact_id: str):
        try:
            fact = self.links.lock_fact(attribution_fact_id)
            if fact is None:
                raise ValueError("attribution fact does not exist")
            if fact.fact_kind != "CONVERSION_REPORTED":
                raise ValueError("attribution fact must be CONVERSION_REPORTED")
            if fact.affiliate_conversion_id is None:
                raise ValueError("conversion fact does not reference a conversion")
            conversion_id = fact.affiliate_conversion_id
            self.links.acquire_conversion_lock(conversion_id)
            conversion = self.links.lock_conversion(conversion_id)
            if conversion is None:
                raise ValueError("attribution conversion does not exist")
            earnings = self.links.lock_earnings_for_conversion(conversion.id)
            if not earnings:
                raise ValueError("authoritative earning does not exist")
            if len(earnings) != 1:
                raise ValueError("authoritative earning is ambiguous")
            earning = earnings[0]
            if earning.conversion_id != conversion.id:
                raise ValueError("authoritative earning does not match conversion")

            existing = self.links.by_fact(fact.id)
            if existing is not None:
                self._assert_same(
                    existing, fact_id=fact.id, conversion_id=conversion.id, earning_id=earning.id,
                )
                self.db.commit()
                return existing
            for candidate in (self.links.by_conversion(conversion.id), self.links.by_earning(earning.id)):
                if candidate is not None:
                    self._assert_same(
                        candidate, fact_id=fact.id, conversion_id=conversion.id, earning_id=earning.id,
                    )
                    self.db.commit()
                    return candidate

            digest = earning_link_digest(
                attribution_fact_id=fact.id,
                affiliate_conversion_id=conversion.id,
                affiliate_earning_id=earning.id,
            )
            link = self.links.create(AttributionEarningLink(
                attribution_fact_id=fact.id,
                affiliate_conversion_id=conversion.id,
                affiliate_earning_id=earning.id,
                source_namespace=EARNING_LINK_SOURCE_NAMESPACE,
                source_event_key_digest=digest,
                linkage_fingerprint=earning_link_fingerprint(
                    attribution_fact_id=fact.id,
                    affiliate_conversion_id=conversion.id,
                    affiliate_earning_id=earning.id,
                    source_event_key_digest=digest,
                ),
                observed_at=datetime.now(timezone.utc),
                recorded_at=datetime.now(timezone.utc),
            ))
            self.db.commit()
            self.db.refresh(link)
            return link
        except IntegrityError:
            self.db.rollback()
            raise AttributionEarningLinkConflict("duplicate attribution earning linkage")
        except Exception:
            self.db.rollback()
            raise
