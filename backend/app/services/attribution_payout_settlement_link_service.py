"""Outer-transaction reconciliation of an attributed earning to paid settlement."""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.attribution.payout_settlement_linkage_contracts import (
    SETTLEMENT_LINK_SOURCE_NAMESPACE,
    AttributionPayoutSettlementLinkConflict,
    payout_settlement_link_digest,
    payout_settlement_link_fingerprint,
)
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.repositories.attribution_payout_settlement_link_repository import (
    AttributionPayoutSettlementLinkRepository,
)


class AttributionPayoutSettlementLinkService:
    def __init__(self, db):
        self.db = db
        self.links = AttributionPayoutSettlementLinkRepository(db)

    @staticmethod
    def _assert_same(existing, *, earning_link_id: str, earning_id: int, payout_id: int, attempt_id: int):
        if (
            existing.attribution_earning_link_id != earning_link_id
            or existing.affiliate_earning_id != earning_id
            or existing.affiliate_payout_id != payout_id
            or existing.affiliate_payout_attempt_id != attempt_id
        ):
            raise AttributionPayoutSettlementLinkConflict(
                "attribution payout settlement linkage conflicts with authoritative identity"
            )

    def reconcile(self, *, attribution_earning_link_id: str):
        try:
            earning_link = self.links.lock_earning_link(attribution_earning_link_id)
            if earning_link is None:
                raise ValueError("attribution earning link does not exist")
            earning = self.links.lock_earning(earning_link.affiliate_earning_id)
            if earning is None:
                raise ValueError("authoritative earning does not exist")
            if earning.id != earning_link.affiliate_earning_id:
                raise ValueError("authoritative earning does not match attribution earning link")
            if earning.payout_id is None:
                raise ValueError("authoritative earning has no payout settlement")
            payout_id = earning.payout_id
            self.links.acquire_payout_lock(payout_id)
            payout = self.links.lock_payout(payout_id)
            if payout is None:
                raise ValueError("authoritative payout does not exist")
            if earning.payout_id != payout.id:
                raise ValueError("authoritative earning does not belong to payout")
            if earning.status != "paid" or payout.status != "paid":
                raise ValueError("authoritative payout settlement is not complete")
            completed_attempts = self.links.lock_completed_attempts(payout.id)
            if len(completed_attempts) != 1:
                raise ValueError("authoritative completed payout attempt is ambiguous or missing")
            attempt = completed_attempts[0]
            if attempt.payout_id != payout.id or attempt.status != "completed":
                raise ValueError("authoritative completed payout attempt does not match payout")

            existing = self.links.by_earning_link(earning_link.id)
            if existing is not None:
                self._assert_same(
                    existing, earning_link_id=earning_link.id, earning_id=earning.id,
                    payout_id=payout.id, attempt_id=attempt.id,
                )
                self.db.commit()
                return existing
            existing = self.links.by_earning(earning.id)
            if existing is not None:
                self._assert_same(
                    existing, earning_link_id=earning_link.id, earning_id=earning.id,
                    payout_id=payout.id, attempt_id=attempt.id,
                )
                self.db.commit()
                return existing

            digest = payout_settlement_link_digest(
                attribution_earning_link_id=earning_link.id, affiliate_earning_id=earning.id,
                affiliate_payout_id=payout.id, affiliate_payout_attempt_id=attempt.id,
            )
            link = self.links.create(AttributionPayoutSettlementLink(
                attribution_earning_link_id=earning_link.id,
                affiliate_earning_id=earning.id,
                affiliate_payout_id=payout.id,
                affiliate_payout_attempt_id=attempt.id,
                source_namespace=SETTLEMENT_LINK_SOURCE_NAMESPACE,
                source_event_key_digest=digest,
                linkage_fingerprint=payout_settlement_link_fingerprint(
                    attribution_earning_link_id=earning_link.id, affiliate_earning_id=earning.id,
                    affiliate_payout_id=payout.id, affiliate_payout_attempt_id=attempt.id,
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
            existing = self.links.by_earning_link(attribution_earning_link_id)
            if existing is not None:
                return existing
            raise AttributionPayoutSettlementLinkConflict("duplicate attribution payout settlement linkage")
        except Exception:
            self.db.rollback()
            raise
