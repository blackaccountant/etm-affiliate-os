"""Atomic public redirect bridge for legacy and M10A click evidence."""

from datetime import datetime, timezone

from app.attribution.bridge_contracts import (
    CLICK_FACT_SOURCE_NAMESPACE,
    CLICK_SOURCE_NAMESPACE,
    click_event_digest,
    click_fact_digest,
)
from app.repositories.attribution_bridge_repository import AttributionBridgeRepository
from app.services.affiliate_click_service import AffiliateClickService
from app.services.attribution_click_service import AttributionClickService
from app.services.attribution_fact_service import AttributionFactService


class AttributionRedirectBridgeService:
    def __init__(self, db):
        self.db = db
        self.bridge = AttributionBridgeRepository(db)
        self.legacy_clicks = AffiliateClickService(db)
        self.attribution_clicks = AttributionClickService(db)
        self.facts = AttributionFactService(db)

    def record(
        self, *, tracking_code: str, event_id: object | None,
        ip_address: str | None = None, user_agent: str | None = None,
        occurred_at: datetime | None = None,
    ):
        try:
            link = self.bridge.link_by_tracking_code(tracking_code)
            if link is None:
                raise ValueError("Affiliate link not found")
            if not link.is_active:
                raise ValueError("Affiliate link is inactive")
            if link.attribution_context_id is None:
                raise ValueError("affiliate link is not attribution-enabled")

            canonical_event_id, event_digest = click_event_digest(event_id)
            self.bridge.acquire_identity_lock(CLICK_SOURCE_NAMESPACE, event_digest)
            existing = self.bridge.attribution_click_by_source(
                CLICK_SOURCE_NAMESPACE, event_digest,
            )
            occurred = (
                occurred_at
                if occurred_at is not None
                else (existing.occurred_at if existing is not None else datetime.now(timezone.utc))
            )

            if existing is None:
                legacy_click = self.legacy_clicks._record_click_uncommitted(
                    tracking_code=tracking_code,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            else:
                legacy_click = self.bridge.legacy_click_by_attribution_click(existing.id)

            attribution_click = self.attribution_clicks.record(
                attribution_context_id=link.attribution_context_id,
                affiliate_link_id=link.id,
                source_namespace=CLICK_SOURCE_NAMESPACE,
                source_event_key_digest=event_digest,
                occurred_at=occurred,
            )
            if legacy_click is None:
                legacy_click = self.legacy_clicks._record_click_uncommitted(
                    tracking_code=tracking_code,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            if legacy_click.attribution_click_id is None:
                legacy_click.attribution_click_id = attribution_click.id
                self.db.flush()
            elif legacy_click.attribution_click_id != attribution_click.id:
                raise ValueError("legacy click correlation does not match attribution click")

            fact = self.facts.append(
                fact_kind="CLICK_RECORDED",
                source_namespace=CLICK_FACT_SOURCE_NAMESPACE,
                source_event_key_digest=click_fact_digest(event_digest),
                occurred_at=occurred,
                attribution_context_id=link.attribution_context_id,
                attribution_click_id=attribution_click.id,
                affiliate_link_id=link.id,
            )
            self.db.commit()
            return {
                "event_id": canonical_event_id,
                "link": link,
                "legacy_click": legacy_click,
                "attribution_click": attribution_click,
                "fact": fact,
            }
        except Exception:
            self.db.rollback()
            raise
