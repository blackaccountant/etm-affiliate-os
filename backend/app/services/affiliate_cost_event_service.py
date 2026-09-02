"""Validation and idempotent recording for immutable cost authority."""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError

from app.affiliate_financial.cost_event_contracts import ALLOCATION_SCOPES, AffiliateCostEventRecord
from app.attribution.contracts import AttributionIdempotencyConflict, canonical_fingerprint
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.content_generation_run import ContentGenerationRun
from app.models.distribution_run import DistributionRun
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.outreach_provider_dispatch import OutreachProviderDispatch
from app.repositories.affiliate_cost_event_repository import AffiliateCostEventRepository

CORRELATIONS = ("product_id", "affiliate_program_id", "content_asset_id", "content_generation_run_id", "distribution_run_id", "affiliate_link_id", "affiliate_conversion_id", "affiliate_earning_id", "affiliate_payout_id", "affiliate_payout_attempt_id", "outreach_provider_dispatch_id")
REVENUE_CORRELATIONS = frozenset({"product_id", "affiliate_program_id", "affiliate_link_id", "affiliate_conversion_id", "affiliate_earning_id", "affiliate_payout_id", "affiliate_payout_attempt_id"})
MODELS = {"product_id": Product, "affiliate_program_id": AffiliateProgram, "content_asset_id": AffiliateContentAsset, "content_generation_run_id": ContentGenerationRun, "distribution_run_id": DistributionRun, "affiliate_link_id": AffiliateLink, "affiliate_conversion_id": AffiliateConversion, "affiliate_earning_id": AffiliateEarning, "affiliate_payout_id": AffiliatePayout, "affiliate_payout_attempt_id": AffiliatePayoutAttempt, "outreach_provider_dispatch_id": OutreachProviderDispatch}


class AffiliateCostEventConflict(AttributionIdempotencyConflict): pass


class AffiliateCostEventService:
    def __init__(self, db): self.db = db; self.repo = AffiliateCostEventRepository(db)
    @staticmethod
    def _text(value, pattern, field):
        text = value.strip().lower() if isinstance(value, str) else ""
        if not re.fullmatch(pattern, text): raise ValueError(f"{field} is invalid")
        return text
    @staticmethod
    def _currency(value):
        text = value.strip().upper() if isinstance(value, str) else ""
        if not re.fullmatch(r"[A-Z]{3}", text): raise ValueError("currency is invalid")
        return text
    @staticmethod
    def _amount(value):
        try: amount = Decimal(str(value))
        except (InvalidOperation, ValueError): raise ValueError("amount is invalid")
        if not amount.is_finite() or amount <= 0: raise ValueError("amount must be positive")
        return amount.quantize(Decimal("0.01"))
    def record(self, request):
        amount=self._amount(request.amount); currency=self._currency(request.currency)
        cost_type=self._text(request.cost_type, r"[a-z][a-z0-9._-]{0,62}", "cost_type")
        scope=self._text(request.allocation_scope, r"[a-z]+", "allocation_scope")
        if scope not in ALLOCATION_SCOPES: raise ValueError("allocation_scope is invalid")
        namespace=self._text(request.source_namespace, r"[a-z][a-z0-9.-]{0,62}", "source_namespace")
        if not isinstance(request.source_event_key, str) or not request.source_event_key.strip(): raise ValueError("source_event_key is required")
        digest=hashlib.sha256(request.source_event_key.strip().encode("utf-8")).hexdigest()
        correlations={name:getattr(request,name) for name in CORRELATIONS if getattr(request,name) is not None}
        if scope == "direct" and not correlations: raise ValueError("direct cost requires explicit correlation")
        if scope == "global" and REVENUE_CORRELATIONS.intersection(correlations): raise ValueError("global cost cannot carry revenue correlation")
        for name, value in correlations.items():
            if self.db.get(MODELS[name], value) is None: raise ValueError(f"{name} does not exist")
        fingerprint=canonical_fingerprint("m10a9a-cost-event-v1", {"amount":str(amount),"currency":currency,"cost_type":cost_type,"allocation_scope":scope,"source_namespace":namespace,"source_event_digest":digest,"correlations":correlations})
        existing=self.repo.by_source(namespace,digest)
        if existing is not None:
            if existing.fingerprint != fingerprint: raise AffiliateCostEventConflict("conflicting cost-event replay")
            return self._record(existing)
        event=AffiliateCostEvent(amount=amount,currency=currency,cost_type=cost_type,allocation_scope=scope,source_namespace=namespace,source_event_digest=digest,fingerprint=fingerprint,**correlations)
        try:
            self.repo.add(event); self.db.commit(); self.db.refresh(event)
        except IntegrityError:
            self.db.rollback(); existing=self.repo.by_source(namespace,digest)
            if existing is None or existing.fingerprint != fingerprint: raise AffiliateCostEventConflict("conflicting cost-event replay")
            event=existing
        return self._record(event)
    @staticmethod
    def _record(event): return AffiliateCostEventRecord(event.id,event.amount,event.currency,event.cost_type,event.allocation_scope,event.source_namespace,event.source_event_digest,event.fingerprint)
