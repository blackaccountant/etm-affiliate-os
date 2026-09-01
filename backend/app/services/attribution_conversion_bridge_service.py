"""Atomic conversion/earning observation bridge into the M10A fact ledger."""

from decimal import Decimal
from typing import Optional

from app.attribution.bridge_contracts import (
    CONVERSION_FACT_SOURCE_NAMESPACE,
    bridge_digest,
    conversion_fact_digest,
    legacy_utc,
    opaque_event_id,
)
from app.repositories.attribution_bridge_repository import AttributionBridgeRepository
from app.services.affiliate_conversion_service import AffiliateConversionService
from app.services.attribution_fact_service import AttributionFactService


class AttributionConversionBridgeService:
    def __init__(self, db):
        self.db = db
        self.bridge = AttributionBridgeRepository(db)
        self.conversions = AffiliateConversionService(db)
        self.facts = AttributionFactService(db)

    def _resolve_link(self, affiliate_link_id, tracking_code):
        if affiliate_link_id is not None:
            return self.bridge.get_link(affiliate_link_id)
        if tracking_code:
            return self.bridge.link_by_tracking_code(tracking_code)
        return None

    def record(
        self, *, affiliate_program_id: int, sale_amount: Decimal,
        currency: str = "USD", affiliate_link_id: Optional[int] = None,
        tracking_code: Optional[str] = None,
        external_conversion_id: Optional[str] = None,
        customer_reference: Optional[str] = None,
        conversion_status: str = "approved",
        commission_rate: Optional[Decimal] = None,
        source: str = "api", metadata_json: Optional[str] = None,
        attribution_click_key: Optional[str] = None,
    ):
        try:
            link = self._resolve_link(affiliate_link_id, tracking_code)
            if link is None:
                raise ValueError("Affiliate link not found")
            if link.attribution_context_id is None:
                raise ValueError("affiliate link is not attribution-enabled")
            context = self.bridge.get_context(link.attribution_context_id)
            if context is None:
                raise ValueError("attribution context does not exist")
            if link.affiliate_program_id != affiliate_program_id or context.affiliate_program_id != affiliate_program_id:
                raise ValueError("affiliate link and context do not match affiliate program")

            external_id = self.conversions._external_id(external_conversion_id)
            if external_id is None:
                raise ValueError("attributed conversion requires external_conversion_id")
            lock_digest = bridge_digest(
                "m10a3-conversion-lock-v1",
                {"affiliate_program_id": affiliate_program_id, "external_conversion_id": external_id},
            )
            self.bridge.acquire_identity_lock("m10a3.conversion", lock_digest)

            attribution_click = None
            if attribution_click_key is not None:
                click_key = opaque_event_id(attribution_click_key)
                attribution_click = self.bridge.attribution_click_by_key(click_key)
                if attribution_click is None:
                    raise ValueError("attribution click does not exist")
                if (
                    attribution_click.attribution_context_id != context.id
                    or attribution_click.affiliate_link_id != link.id
                ):
                    raise ValueError("attribution click does not match conversion link and context")

            conversion, earning, created = self.conversions._create_conversion_uncommitted(
                affiliate_program_id=affiliate_program_id,
                sale_amount=sale_amount,
                currency=currency,
                affiliate_link_id=link.id,
                tracking_code=None,
                external_conversion_id=external_id,
                customer_reference=customer_reference,
                conversion_status=conversion_status,
                commission_rate=commission_rate,
                source=source,
                metadata_json=metadata_json,
                strict_replay=True,
            )
            occurred = legacy_utc(conversion.created_at)
            fact = self.facts.append(
                fact_kind="CONVERSION_REPORTED",
                source_namespace=CONVERSION_FACT_SOURCE_NAMESPACE,
                source_event_key_digest=conversion_fact_digest(conversion.id),
                occurred_at=occurred,
                attribution_context_id=context.id,
                attribution_click_id=attribution_click.id if attribution_click else None,
                affiliate_link_id=link.id,
                affiliate_conversion_id=conversion.id,
            )
            self.db.commit()
            self.db.refresh(conversion)
            return {
                "conversion": conversion,
                "earning": earning,
                "fact": fact,
                "created": created,
            }
        except Exception:
            self.db.rollback()
            raise
