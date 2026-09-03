"""Guarded PostgreSQL qualification for the schema-free M11A1 signal adapter."""

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
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.affiliate_financial.global_cost_allocation_contracts import (
    GlobalCostAllocationLineRequest,
    RecordGlobalCostAllocationRequest,
)
from app.attribution.operating_profit_projection_contracts import OperatingProfitProjectionRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.optimization.operating_profit_signal_contracts import OperatingProfitSignalRequest
from app.services.affiliate_cost_allocation_service import AffiliateCostAllocationService
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.affiliate_global_cost_allocation_service import AffiliateGlobalCostAllocationService
from app.services.attribution_operating_profit_projection_service import (
    AttributionOperatingProfitProjectionService,
)
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import (
    AttributionPayoutSettlementLinkService,
)
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


ROLE = os.getenv("ETM_G5_M11A1_DB_ROLE")
RAW_URL = os.getenv("ETM_G5_M11A1_DATABASE_URL")
if not RAW_URL:
    pytest.skip("requires guarded ETM_G5_M11A1_DATABASE_URL", allow_module_level=True)
URL = make_url(RAW_URL)
if (
    ROLE != "qualification"
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != "etm_g5_m11a1_operating_profit_signal_qualification"
):
    raise RuntimeError("M11A1 qualification database guard failed")


def _session():
    from sqlalchemy import create_engine

    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, currency="USD", product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id else Product(
            name=token, website=f"https://{token}.invalid", category="test",
            affiliate_program="test", commission_type="percentage", commission_value="10",
            affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active",
        )
        if not product_id:
            db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id else AffiliateProgram(
            product_id=product.id, program_name=token, commission_type="percentage",
            commission_value="10", status="active",
        )
        if not program_id:
            db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token)
        db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token)
        db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id, attribution_publication_id=publication.id,
        )
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id, attribution_context_id=context.id, name=token,
            destination_url="https://private.invalid", content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id, affiliate_link_id=link.id,
            external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"),
            currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}),
        )
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(
            affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency,
            status="paid", paid_at=now, created_at=now, updated_at=now,
        )
        db.add(payout); db.flush()
        earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(
            payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency,
            status="completed", provider="manual", idempotency_key=token, started_at=now,
            completed_at=now, created_at=now, updated_at=now,
        )
        db.add(attempt); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"earning": earning.id, "conversion": result["conversion"].id, "currency": currency}
    finally:
        db.close()


def _cost(identity, amount, scope, **fields):
    db = _session()
    try:
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(
            amount=amount, currency=identity["currency"], cost_type="provider_fee",
            allocation_scope=scope, source_namespace="m11a1.cost", source_event_key=uuid4().hex,
            **fields,
        ))
    finally:
        db.close()


def _global(cost, lines):
    db = _session()
    try:
        return AffiliateGlobalCostAllocationService(db).record(RecordGlobalCostAllocationRequest(
            cost.id,
            tuple(GlobalCostAllocationLineRequest(identity["earning"], amount) for identity, amount in lines),
            "explicit-v1", "m11a1.global", uuid4().hex,
        ))
    finally:
        db.close()


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("earning") == identity["earning"])


def test_current_head_is_inherited_without_migration():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally:
        db.close()


def test_signal_maps_real_m10a9f_rows_once_without_sql_before_upstream_or_network(monkeypatch):
    positive, zero, negative, eur = _settled(), _settled(), _settled(), _settled(currency="EUR")
    _global(_cost(positive, Decimal("30.00"), "global"), ((positive, Decimal("30.00")),))
    _global(_cost(zero, Decimal("100.00"), "global"), ((zero, Decimal("100.00")),))
    _global(_cost(negative, Decimal("120.00"), "global"), ((negative, Decimal("120.00")),))
    _global(_cost(eur, Decimal("20.00"), "global"), ((eur, Decimal("20.00")),))
    db = _session()
    statements, calls = [], []
    engine = db.get_bind()
    listener = lambda *args: statements.append(" ".join(args[2].upper().split()))
    event.listen(engine, "before_cursor_execute", listener)
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    try:
        request = OperatingProfitSignalRequest(("earning",), "USD")
        service = OperatingProfitSignalService(db)
        real = service._operating_profit.project
        service._operating_profit.project = lambda value: calls.append(value) or real(value)
        signals = service.project(request)
        assert len(calls) == 1
        assert _owned(signals, positive).operating_profit == Decimal("70.00")
        assert _owned(signals, zero).operating_profit == Decimal("0.00")
        assert _owned(signals, negative).operating_profit == Decimal("-20.00")
        assert all(dict(signal.dimensions).get("earning") != eur["earning"] for signal in signals)
        setup = [index for index, sql in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql]
        assert len(setup) == 1 and setup[0] == 0
        with pytest.raises(Exception):
            db.execute(text(
                "INSERT INTO affiliate_cost_events "
                "(id,amount,currency,cost_type,allocation_scope,source_namespace,source_event_digest,fingerprint,created_at) "
                "VALUES (:id,1,'USD','x','global','x',:digest,:fingerprint,now())"
            ), {"id": str(uuid4()), "digest": uuid4().hex * 2, "fingerprint": "f" * 64})
        db.rollback()
        payload = str([asdict(signal) for signal in signals])
        assert all(value not in payload for value in ("m11a1.cost", "m11a1.global", "private"))
    finally:
        event.remove(engine, "before_cursor_execute", listener)
        db.close()


def test_signal_matches_direct_m10a9f_rows_and_is_deterministic():
    identity = _settled()
    _global(_cost(identity, Decimal("30.00"), "global"), ((identity, Decimal("30.00")),))
    request = OperatingProfitSignalRequest(("earning",), "USD")
    reader = _session()
    try:
        signals = OperatingProfitSignalService(reader).project(request)
        replay = OperatingProfitSignalService(reader).project(request)
        assert signals == replay
    finally:
        reader.close()
    upstream_reader = _session()
    try:
        upstream = AttributionOperatingProfitProjectionService(upstream_reader).project(
            OperatingProfitProjectionRequest(("earning",), "USD"),
        )
    finally:
        upstream_reader.close()
    signal, row = _owned(signals, identity), _owned(upstream, identity)
    assert signal.currency == row.currency and signal.dimensions == row.dimensions
    assert signal.source_semantics == row.semantics
    assert all(getattr(signal, name) == getattr(row, name) for name in (
        "net_realized_commission", "directly_attributable_cost", "contribution_profit",
        "allocated_shared_cost", "allocated_contribution_profit", "allocated_global_cost",
        "operating_profit",
    ))


def test_a_b_a_c_snapshot_behavior_is_inherited_from_m10a9f():
    identity = _settled()
    request = OperatingProfitSignalRequest(("earning",), "USD")
    reader = _session()
    try:
        service = OperatingProfitSignalService(reader)
        before = _owned(service.project(request), identity).operating_profit
        _global(_cost(identity, Decimal("25.00"), "global"), ((identity, Decimal("25.00")),))
        same_snapshot = _owned(service.project(request), identity).operating_profit
        assert (before, same_snapshot) == (Decimal("100.00"), Decimal("100.00"))
    finally:
        reader.close()
    fresh = _session()
    try:
        after = _owned(OperatingProfitSignalService(fresh).project(request), identity).operating_profit
        assert after == Decimal("75.00")
    finally:
        fresh.close()
