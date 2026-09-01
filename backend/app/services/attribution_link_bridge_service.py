"""Atomic one-time binding of legacy affiliate links to M10A contexts."""

from app.attribution.bridge_contracts import (
    LINK_SOURCE_NAMESPACE,
    legacy_utc,
    link_binding_digest,
)
from app.models.affiliate_program import AffiliateProgram
from app.repositories.attribution_bridge_repository import AttributionBridgeRepository
from app.services.affiliate_link_service import AffiliateLinkService
from app.services.attribution_fact_service import AttributionFactService


class AttributionLinkBridgeService:
    def __init__(self, db):
        self.db = db
        self.bridge = AttributionBridgeRepository(db)
        self.links = AffiliateLinkService(db)
        self.facts = AttributionFactService(db)

    def _validate_context(self, affiliate_program_id: int, context_id: str):
        program = self.db.get(AffiliateProgram, affiliate_program_id)
        context = self.bridge.get_context(context_id)
        if program is None:
            raise ValueError("affiliate program does not exist")
        if context is None:
            raise ValueError("attribution context does not exist")
        if context.affiliate_program_id != program.id:
            raise ValueError("affiliate program does not match attribution context")
        return context

    def _append_binding_fact(self, link, context):
        return self.facts.append(
            fact_kind="LINK_BOUND",
            source_namespace=LINK_SOURCE_NAMESPACE,
            source_event_key_digest=link_binding_digest(link.id, context.id),
            occurred_at=legacy_utc(link.created_at, fallback=context.created_at),
            attribution_context_id=context.id,
            affiliate_link_id=link.id,
        )

    def create_bound_link(
        self, *, affiliate_program_id: int, attribution_context_id: str,
        name: str, destination_url: str, content_asset_id: int | None = None,
    ):
        try:
            context = self._validate_context(affiliate_program_id, attribution_context_id)
            link = self.links._create_link_uncommitted(
                affiliate_program_id=affiliate_program_id,
                name=name,
                destination_url=destination_url,
                content_asset_id=content_asset_id,
                attribution_context_id=context.id,
            )
            self._append_binding_fact(link, context)
            self.db.commit()
            self.db.refresh(link)
            return link
        except Exception:
            self.db.rollback()
            raise

    def bind_existing(self, *, affiliate_link_id: int, attribution_context_id: str):
        try:
            unlocked = self.bridge.get_link(affiliate_link_id)
            if unlocked is None:
                raise ValueError("affiliate link does not exist")
            context = self._validate_context(
                unlocked.affiliate_program_id, attribution_context_id,
            )
            digest = link_binding_digest(unlocked.id, context.id)
            self.bridge.acquire_identity_lock(LINK_SOURCE_NAMESPACE, digest)
            link = self.bridge.bind_link_context(unlocked.id, context.id)
            fact = self._append_binding_fact(link, context)
            self.db.commit()
            self.db.refresh(link)
            return link, fact
        except Exception:
            self.db.rollback()
            raise
