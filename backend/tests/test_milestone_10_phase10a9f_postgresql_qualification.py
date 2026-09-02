"""Guarded PostgreSQL qualification for the read-only M10A9F operating-profit projection."""
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.affiliate_financial.cost_allocation_contracts import RecordSharedCostAllocationRequest, SharedCostAllocationLineRequest
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.affiliate_financial.global_cost_allocation_contracts import RecordGlobalCostAllocationRequest, GlobalCostAllocationLineRequest
from app.attribution.allocated_contribution_profit_projection_contracts import AllocatedContributionProfitProjectionRequest
from app.attribution.operating_profit_projection_contracts import OperatingProfitProjectionRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.affiliate_cost_allocation_service import AffiliateCostAllocationService
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.affiliate_global_cost_allocation_service import AffiliateGlobalCostAllocationService
from app.services.attribution_allocated_contribution_profit_projection_service import AttributionAllocatedContributionProfitProjectionService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_operating_profit_projection_service import AttributionOperatingProfitProjectionService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService


ROLE, raw = os.getenv("ETM_G5_M10A9F_DB_ROLE"), os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("requires guarded ETM_G5_DATABASE_URL", allow_module_level=True)
url = make_url(raw)
if ROLE != "qualification" or not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == "etm_g5_m10a9f_operating_profit_qualification"):
    raise RuntimeError("M10A9F qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, currency="USD", product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if not product_id: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if not program_id: db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id); db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"), currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush(); earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now); db.add(attempt); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"earning": earning.id, "conversion": result["conversion"].id, "product": product.id, "program": program.id, "currency": currency}
    finally: db.close()


def _cost(identity, amount, scope, **fields):
    db = _session()
    try:
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(amount=amount, currency=identity["currency"], cost_type="provider_fee", allocation_scope=scope, source_namespace="m10a9f.cost", source_event_key=uuid4().hex, **fields))
    finally: db.close()


def _shared(cost, lines):
    db = _session()
    try:
        return AffiliateCostAllocationService(db).record(RecordSharedCostAllocationRequest(cost.id, tuple(SharedCostAllocationLineRequest(item["earning"], amount) for item, amount in lines), "explicit-v1", "m10a9f.shared", uuid4().hex))
    finally: db.close()


def _global(cost, lines, source=None):
    db = _session()
    try:
        return AffiliateGlobalCostAllocationService(db).record(RecordGlobalCostAllocationRequest(cost.id, tuple(GlobalCostAllocationLineRequest(item["earning"], amount) for item, amount in lines), "explicit-v1", "m10a9f.global", source or uuid4().hex))
    finally: db.close()


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("earning") == identity["earning"])


def test_current_head_no_migration_and_read_surface():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally: db.close()


def test_arithmetic_grouping_revenue_rooted_privacy_and_single_m10a9d_composition(monkeypatch):
    first = _settled(); second = _settled(product_id=first["product"], program_id=first["program"]); outside = _settled(currency="EUR")
    _cost(first, Decimal("20.00"), "direct", affiliate_earning_id=first["earning"], affiliate_conversion_id=first["conversion"])
    _shared(_cost(first, Decimal("10.00"), "shared"), ((first, Decimal("10.00")),))
    global_cost = _cost(first, Decimal("30.00"), "global"); allocation = _global(global_cost, ((first, Decimal("20.00")), (second, Decimal("10.00"))))
    _global(_cost(outside, Decimal("9.00"), "global"), ((outside, Decimal("9.00")),))
    calls = {"d": 0, "requests": 0}
    real = AttributionAllocatedContributionProfitProjectionService.project
    monkeypatch.setattr(AttributionAllocatedContributionProfitProjectionService, "project", lambda service, request: calls.__setitem__("d", calls["d"] + 1) or real(service, request))
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    db = _session()
    try:
        service = AttributionOperatingProfitProjectionService(db)
        rows = service.project(OperatingProfitProjectionRequest(("earning",), "USD"))
        one, two = _owned(rows, first), _owned(rows, second)
        grouped = service.project(OperatingProfitProjectionRequest(("affiliate_program",), "USD"))
        assert (one.allocated_contribution_profit, one.allocated_global_cost, one.operating_profit) == (Decimal("70.00"), Decimal("20.00"), Decimal("50.00"))
        assert (two.allocated_contribution_profit, two.allocated_global_cost, two.operating_profit) == (Decimal("100.00"), Decimal("10.00"), Decimal("90.00"))
        assert calls["d"] == 1 and all(dict(row.dimensions).get("earning") != outside["earning"] for row in rows)
        group = next(row for row in grouped if dict(row.dimensions).get("affiliate_program") == first["program"])
        assert (group.allocated_contribution_profit, group.allocated_global_cost, group.operating_profit) == (Decimal("170.00"), Decimal("30.00"), Decimal("140.00"))
        payload = json.dumps([asdict(row) for row in rows], default=str)
        assert all(value not in payload for value in (global_cost.id, allocation.id, "m10a9f.global", "private"))
    finally: db.close()


def test_currency_negative_zero_and_read_only_snapshot(monkeypatch):
    negative, zero, eur = _settled(), _settled(), _settled(currency="EUR")
    _global(_cost(negative, Decimal("120.00"), "global"), ((negative, Decimal("120.00")),))
    _global(_cost(zero, Decimal("100.00"), "global"), ((zero, Decimal("100.00")),))
    _global(_cost(eur, Decimal("20.00"), "global"), ((eur, Decimal("20.00")),))
    db = _session(); statements=[]; engine=db.get_bind()
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(" ".join(args[2].upper().split())))
    try:
        rows = AttributionOperatingProfitProjectionService(db).project(OperatingProfitProjectionRequest(("earning",)))
        assert _owned(rows, negative).operating_profit == Decimal("-20.00")
        assert _owned(rows, zero).operating_profit == Decimal("0.00")
        assert _owned(rows, eur).currency == "EUR"
        setup=[i for i, sql in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql]
        reads=[i for i, sql in enumerate(statements) if "AFFILIATE_GLOBAL_COST_ALLOCATION_LINES" in sql]
        assert len(setup) == 1 and reads and setup[0] < reads[0]
        with pytest.raises(Exception): db.execute(text("INSERT INTO affiliate_cost_events (id,amount,currency,cost_type,allocation_scope,source_namespace,source_event_digest,fingerprint,created_at) VALUES (:id,1,'USD','x','global','x',:digest,:fingerprint,now())"), {"id":str(uuid4()), "digest":uuid4().hex*2, "fingerprint":"f"*64})
        db.rollback()
    finally: event.remove(engine, "before_cursor_execute", event.listeners(engine, "before_cursor_execute")[-1]) if False else None; db.close()
